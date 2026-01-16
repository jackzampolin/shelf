package endpoints

import (
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/epub"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// EpubExportResponse is returned when an epub is generated.
type EpubExportResponse struct {
	BookID       string `json:"book_id"`
	Title        string `json:"title"`
	Author       string `json:"author"`
	ChapterCount int    `json:"chapter_count"`
	FilePath     string `json:"file_path"`
	FileSize     int64  `json:"file_size"`
	DownloadURL  string `json:"download_url"`
	CreatedAt    string `json:"created_at"`
}

// ExportEpubEndpoint handles POST /api/books/{book_id}/export/epub.
type ExportEpubEndpoint struct{}

func (e *ExportEpubEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/books/{book_id}/export/epub", e.handler
}

func (e *ExportEpubEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Export book as ePub
//	@Description	Generate an ePub 3.0 file from a processed book
//	@Tags			books,export
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{object}	EpubExportResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/export/epub [post]
func (e *ExportEpubEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	// Check book status
	status, _ := bookData["status"].(string)
	if status != "complete" && status != "processing" {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("book is not ready for export (status: %s)", status))
		return
	}

	// Load chapters
	chapterQuery := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}) {
			_docID
			entry_id
			title
			level
			level_name
			entry_number
			matter_type
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

	// Convert to epub.Chapter
	var chapters []epub.Chapter
	for _, ch := range chapterList {
		chData, ok := ch.(map[string]any)
		if !ok {
			continue
		}

		// Skip chapters without polished text
		polishComplete, _ := chData["polish_complete"].(bool)
		if !polishComplete {
			continue
		}

		chapter := epub.Chapter{
			ID:           getString(chData, "entry_id"),
			Title:        getString(chData, "title"),
			Level:        getInt(chData, "level"),
			LevelName:    getString(chData, "level_name"),
			EntryNumber:  getString(chData, "entry_number"),
			MatterType:   getString(chData, "matter_type"),
			PolishedText: getString(chData, "polished_text"),
			SortOrder:    getInt(chData, "sort_order"),
		}
		chapters = append(chapters, chapter)
	}

	if len(chapters) == 0 {
		writeError(w, http.StatusBadRequest, "no chapters with polished text found")
		return
	}

	// Sort by sort_order
	sortChapters(chapters)

	// Build epub
	book := epub.Book{
		ID:       bookID,
		Title:    getString(bookData, "title"),
		Author:   getString(bookData, "author"),
		Language: "en",
	}

	builder := epub.NewBuilder(book, chapters)

	// Create export directory
	exportDir := filepath.Join(homeDir.ExportsDir(), bookID)
	if err := os.MkdirAll(exportDir, 0755); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create export directory: %v", err))
		return
	}

	// Generate filename
	safeTitle := sanitizeFilename(book.Title)
	if safeTitle == "" {
		safeTitle = "book"
	}
	filename := fmt.Sprintf("%s.epub", safeTitle)
	outputPath := filepath.Join(exportDir, filename)

	// Build epub
	if err := builder.Build(outputPath); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to generate epub: %v", err))
		return
	}

	// Get file info
	info, err := os.Stat(outputPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to stat epub file: %v", err))
		return
	}

	resp := EpubExportResponse{
		BookID:       bookID,
		Title:        book.Title,
		Author:       book.Author,
		ChapterCount: len(chapters),
		FilePath:     outputPath,
		FileSize:     info.Size(),
		DownloadURL:  fmt.Sprintf("/api/books/%s/export/epub/download", bookID),
		CreatedAt:    time.Now().UTC().Format(time.RFC3339),
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *ExportEpubEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "export-epub <book_id>",
		Short: "Export book as ePub",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp EpubExportResponse
			if err := client.Post(ctx, fmt.Sprintf("/api/books/%s/export/epub", bookID), nil, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// DownloadEpubEndpoint handles GET /api/books/{book_id}/export/epub/download.
type DownloadEpubEndpoint struct{}

func (e *DownloadEpubEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/export/epub/download", e.handler
}

func (e *DownloadEpubEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Download ePub file
//	@Description	Download the generated ePub file for a book
//	@Tags			books,export
//	@Produce		application/epub+zip
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{file}		file
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/export/epub/download [get]
func (e *DownloadEpubEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	// Find epub file in export directory
	exportDir := filepath.Join(homeDir.ExportsDir(), bookID)
	entries, err := os.ReadDir(exportDir)
	if err != nil {
		writeError(w, http.StatusNotFound, "no epub export found - run export first")
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

func (e *DownloadEpubEndpoint) Command(getServerURL func() string) *cobra.Command {
	var outputPath string
	cmd := &cobra.Command{
		Use:   "download-epub <book_id>",
		Short: "Download ePub file",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			data, err := client.GetRaw(ctx, fmt.Sprintf("/api/books/%s/export/epub/download", bookID))
			if err != nil {
				return err
			}

			if outputPath == "" {
				outputPath = fmt.Sprintf("%s.epub", bookID)
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

// Helper functions

func sortChapters(chapters []epub.Chapter) {
	// Simple bubble sort by sort_order
	for i := 0; i < len(chapters)-1; i++ {
		for j := 0; j < len(chapters)-i-1; j++ {
			if chapters[j].SortOrder > chapters[j+1].SortOrder {
				chapters[j], chapters[j+1] = chapters[j+1], chapters[j]
			}
		}
	}
}

func sanitizeFilename(name string) string {
	// Remove or replace problematic characters
	replacer := strings.NewReplacer(
		"/", "_",
		"\\", "_",
		":", "_",
		"*", "_",
		"?", "_",
		"\"", "_",
		"<", "_",
		">", "_",
		"|", "_",
	)
	name = replacer.Replace(name)
	// Trim spaces and dots from ends
	name = strings.Trim(name, " .")
	// Limit length
	if len(name) > 100 {
		name = name[:100]
	}
	return name
}
