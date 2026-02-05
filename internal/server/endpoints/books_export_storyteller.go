package endpoints

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/epub"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// StorytellerExportResponse is returned when an EPUB with Media Overlays is generated.
type StorytellerExportResponse struct {
	BookID          string `json:"book_id"`
	Title           string `json:"title"`
	Author          string `json:"author"`
	ChapterCount    int    `json:"chapter_count"`
	AudioChapters   int    `json:"audio_chapters"`
	TotalDurationMS int    `json:"total_duration_ms"`
	FilePath        string `json:"file_path"`
	FileSize        int64  `json:"file_size"`
	DownloadURL     string `json:"download_url"`
	CreatedAt       string `json:"created_at"`
}

// ExportStorytellerEndpoint handles POST /api/books/{book_id}/export/storyteller.
type ExportStorytellerEndpoint struct{}

func (e *ExportStorytellerEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/books/{book_id}/export/storyteller", e.handler
}

func (e *ExportStorytellerEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Export book as EPUB with Media Overlays for Storyteller
//	@Description	Generate an EPUB 3.0 file with synchronized audio (Media Overlays) for use with Storyteller
//	@Tags			books,export,storyteller
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{object}	StorytellerExportResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/export/storyteller [post]
func (e *ExportStorytellerEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	if err := defra.ValidateID(bookID); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid book_id: %v", err))
		return
	}

	ctx := r.Context()
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		writeError(w, http.StatusServiceUnavailable, "home directory not configured")
		return
	}

	// Load book metadata
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			_docID
			title
			author
			page_count
			status
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query book: %v", err))
		return
	}

	books, ok := bookResp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		writeError(w, http.StatusNotFound, "book not found")
		return
	}

	bookData, ok := books[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "invalid book data")
		return
	}

	// Load chapters with their DocIDs
	chapterQuery := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}) {
			_docID
			entry_id
			title
			level
			level_name
			entry_number
			matter_type
			audio_include
			polished_text
			sort_order
			polish_complete
		}
	}`, bookID)

	chapterResp, err := defraClient.Execute(ctx, chapterQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query chapters: %v", err))
		return
	}

	chapterList, ok := chapterResp.Data["Chapter"].([]any)
	if !ok || len(chapterList) == 0 {
		writeError(w, http.StatusBadRequest, "no chapters found - book processing may not be complete")
		return
	}

	// Build chapter list aligned with TTS chapter filtering/indexing rules.
	var chapters []epub.Chapter
	for _, ch := range chapterList {
		chData, ok := ch.(map[string]any)
		if !ok {
			continue
		}

		polishComplete, _ := chData["polish_complete"].(bool)
		if !polishComplete {
			continue
		}
		if !resolveStorytellerAudioInclude(chData) {
			continue
		}
		if getString(chData, "polished_text") == "" {
			continue
		}

		sortOrder := getInt(chData, "sort_order")

		chapter := epub.Chapter{
			ID:           getString(chData, "entry_id"),
			Title:        getString(chData, "title"),
			Level:        getInt(chData, "level"),
			LevelName:    getString(chData, "level_name"),
			EntryNumber:  getString(chData, "entry_number"),
			MatterType:   getString(chData, "matter_type"),
			PolishedText: getString(chData, "polished_text"),
			SortOrder:    sortOrder,
		}
		chapters = append(chapters, chapter)
	}

	if len(chapters) == 0 {
		writeError(w, http.StatusBadRequest, "no chapters with polished text found")
		return
	}

	// Sort chapters by sort_order
	sort.Slice(chapters, func(i, j int) bool {
		return chapters[i].SortOrder < chapters[j].SortOrder
	})

	// Load ChapterAudio records
	chapterAudioQuery := fmt.Sprintf(`{
		ChapterAudio(filter: {book_id: {_eq: "%s"}}) {
			_docID
			unique_key
			chapter_idx
			audio_file
			duration_ms
			segment_count
		}
	}`, bookID)

	chapterAudioResp, err := defraClient.Execute(ctx, chapterAudioQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query chapter audio: %v", err))
		return
	}

	// Build ChapterAudio map (chapter_idx -> audio data)
	chapterAudioMap := make(map[int]map[string]any)
	if audioList, ok := chapterAudioResp.Data["ChapterAudio"].([]any); ok {
		for _, a := range audioList {
			if audioData, ok := a.(map[string]any); ok {
				idx := getInt(audioData, "chapter_idx")
				chapterAudioMap[idx] = audioData
			}
		}
	}

	// Load AudioSegment records for timing data
	segmentQuery := fmt.Sprintf(`{
		AudioSegment(filter: {book_id: {_eq: "%s"}}) {
			chapter_idx
			paragraph_idx
			duration_ms
			start_offset_ms
		}
	}`, bookID)

	segmentResp, err := defraClient.Execute(ctx, segmentQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query audio segments: %v", err))
		return
	}

	// Build segments map (chapter_idx -> []AudioSegment)
	segmentsMap := make(map[int][]epub.AudioSegment)
	if segList, ok := segmentResp.Data["AudioSegment"].([]any); ok {
		for _, s := range segList {
			if segData, ok := s.(map[string]any); ok {
				chapterIdx := getInt(segData, "chapter_idx")
				seg := epub.AudioSegment{
					ParagraphIdx:  getInt(segData, "paragraph_idx"),
					DurationMS:    getInt(segData, "duration_ms"),
					StartOffsetMS: getInt(segData, "start_offset_ms"),
				}
				segmentsMap[chapterIdx] = append(segmentsMap[chapterIdx], seg)
			}
		}
	}

	// Sort segments by paragraph_idx within each chapter
	for chIdx := range segmentsMap {
		sort.Slice(segmentsMap[chIdx], func(i, j int) bool {
			return segmentsMap[chIdx][i].ParagraphIdx < segmentsMap[chIdx][j].ParagraphIdx
		})
	}

	// Build epub with Media Overlays
	book := epub.Book{
		ID:       bookID,
		Title:    getString(bookData, "title"),
		Author:   getString(bookData, "author"),
		Language: "en",
	}

	builder := epub.NewMediaOverlayBuilder(book, chapters)
	builder.SetNarrator("Chatterbox TTS")

	// Add audio data for each chapter
	var totalDurationMS int
	var audioChapterCount int
	for i, ch := range chapters {
		if audioData, hasAudio := chapterAudioMap[i]; hasAudio {
			audioFile := getString(audioData, "audio_file")
			durationMS := getInt(audioData, "duration_ms")

			// Get segments for this chapter
			segments := segmentsMap[i]

			chapterAudio := epub.ChapterAudio{
				ChapterID:  ch.ID,
				AudioFile:  audioFile,
				DurationMS: durationMS,
				Segments:   segments,
			}
			builder.AddChapterAudio(ch.ID, chapterAudio)
			totalDurationMS += durationMS
			audioChapterCount++
		}
	}

	if audioChapterCount == 0 {
		writeError(w, http.StatusBadRequest, "no audio data found - generate audio first with TTS")
		return
	}

	// Create export directory
	exportDir := filepath.Join(homeDir.ExportsDir(), bookID, "storyteller")
	if err := os.MkdirAll(exportDir, 0755); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create export directory: %v", err))
		return
	}

	// Generate filename
	safeTitle := sanitizeFilename(book.Title)
	if safeTitle == "" {
		safeTitle = "book"
	}
	filename := fmt.Sprintf("%s-readaloud.epub", safeTitle)
	outputPath := filepath.Join(exportDir, filename)

	// Build epub
	if err := builder.Build(outputPath); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to generate epub with media overlays: %v", err))
		return
	}

	// Get file info
	info, err := os.Stat(outputPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to stat epub file: %v", err))
		return
	}

	resp := StorytellerExportResponse{
		BookID:          bookID,
		Title:           book.Title,
		Author:          book.Author,
		ChapterCount:    len(chapters),
		AudioChapters:   audioChapterCount,
		TotalDurationMS: totalDurationMS,
		FilePath:        outputPath,
		FileSize:        info.Size(),
		DownloadURL:     fmt.Sprintf("/api/books/%s/export/storyteller/download", bookID),
		CreatedAt:       time.Now().UTC().Format(time.RFC3339),
	}

	writeJSON(w, http.StatusOK, resp)
}

func resolveStorytellerAudioInclude(chData map[string]any) bool {
	if include, ok := chData["audio_include"].(bool); ok {
		return include
	}

	switch getString(chData, "matter_type") {
	case "back_matter":
		return false
	case "front_matter", "body":
		return true
	default:
		return true
	}
}

func (e *ExportStorytellerEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "export-storyteller <book_id>",
		Short: "Export book as EPUB with Media Overlays for Storyteller",
		Long:  "Generate an EPUB 3.0 file with synchronized audio (SMIL Media Overlays) for use with Storyteller or other readaloud platforms.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp StorytellerExportResponse
			if err := client.Post(ctx, fmt.Sprintf("/api/books/%s/export/storyteller", bookID), nil, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// DownloadStorytellerEndpoint handles GET /api/books/{book_id}/export/storyteller/download.
type DownloadStorytellerEndpoint struct{}

func (e *DownloadStorytellerEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/export/storyteller/download", e.handler
}

func (e *DownloadStorytellerEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Download Storyteller EPUB file
//	@Description	Download the generated EPUB file with Media Overlays for a book
//	@Tags			books,export,storyteller
//	@Produce		application/epub+zip
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{file}		file
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/export/storyteller/download [get]
func (e *DownloadStorytellerEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	if err := defra.ValidateID(bookID); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid book_id: %v", err))
		return
	}

	ctx := r.Context()
	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		writeError(w, http.StatusServiceUnavailable, "home directory not configured")
		return
	}

	// Find epub file in storyteller export directory
	exportDir := filepath.Join(homeDir.ExportsDir(), bookID, "storyteller")
	entries, err := os.ReadDir(exportDir)
	if err != nil {
		writeError(w, http.StatusNotFound, "no storyteller export found - run export-storyteller first")
		return
	}

	var epubPath string
	for _, entry := range entries {
		if strings.HasSuffix(entry.Name(), ".epub") {
			epubPath = filepath.Join(exportDir, entry.Name())
			break
		}
	}

	if epubPath == "" {
		writeError(w, http.StatusNotFound, "no epub file found")
		return
	}

	// Serve the file
	filename := filepath.Base(epubPath)
	w.Header().Set("Content-Type", "application/epub+zip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	http.ServeFile(w, r, epubPath)
}

func (e *DownloadStorytellerEndpoint) Command(getServerURL func() string) *cobra.Command {
	var outputPath string
	cmd := &cobra.Command{
		Use:   "download-storyteller <book_id>",
		Short: "Download Storyteller EPUB file",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			data, err := client.GetRaw(ctx, fmt.Sprintf("/api/books/%s/export/storyteller/download", bookID))
			if err != nil {
				return err
			}

			if outputPath == "" {
				outputPath = fmt.Sprintf("%s-readaloud.epub", bookID)
			}

			if err := os.WriteFile(outputPath, data, 0644); err != nil {
				return fmt.Errorf("failed to write file: %w", err)
			}

			fmt.Printf("Downloaded to: %s\n", outputPath)
			return nil
		},
	}
	cmd.Flags().StringVarP(&outputPath, "output", "o", "", "Output file path")
	return cmd
}
