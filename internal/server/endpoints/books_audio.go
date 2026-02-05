package endpoints

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/voices"
)

// GenerateAudioRequest is the request body for starting TTS generation.
type GenerateAudioRequest struct {
	Voice  string `json:"voice,omitempty"`  // Optional: voice ID
	Format string `json:"format,omitempty"` // Optional: output format (mp3, wav)
}

// GenerateAudioResponse is returned when TTS generation is started.
type GenerateAudioResponse struct {
	JobID    string `json:"job_id"`
	BookID   string `json:"book_id"`
	Status   string `json:"status"`
	Chapters int    `json:"chapters"`
	Provider string `json:"provider"`
}

// AudioStatusResponse contains audio generation status and files.
type AudioStatusResponse struct {
	BookID          string               `json:"book_id"`
	Status          string               `json:"status"`
	ErrorMessage    string               `json:"error_message,omitempty"`
	Provider        string               `json:"provider,omitempty"`
	Voice           string               `json:"voice,omitempty"`
	Format          string               `json:"format,omitempty"`
	TotalDurationMS int                  `json:"total_duration_ms,omitempty"`
	TotalCostUSD    float64              `json:"total_cost_usd,omitempty"`
	ChapterCount    int                  `json:"chapter_count,omitempty"`
	SegmentCount    int                  `json:"segment_count,omitempty"`
	Chapters        []ChapterAudioStatus `json:"chapters,omitempty"`
}

// ChapterAudioStatus contains status for a single chapter's audio.
type ChapterAudioStatus struct {
	ChapterIdx   int     `json:"chapter_idx"`
	Title        string  `json:"title,omitempty"`
	DurationMS   int     `json:"duration_ms,omitempty"`
	SegmentCount int     `json:"segment_count,omitempty"`
	CostUSD      float64 `json:"cost_usd,omitempty"`
	AudioFile    string  `json:"audio_file,omitempty"`
	DownloadURL  string  `json:"download_url,omitempty"`
}

// GenerateAudioEndpoint handles POST /api/books/{book_id}/generate/audio.
type GenerateAudioEndpoint struct{}

func (e *GenerateAudioEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/books/{book_id}/generate/audio", e.handler
}

func (e *GenerateAudioEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Start TTS audio generation
//	@Description	Start TTS audiobook generation for a book
//	@Tags			books,audio
//	@Accept			json
//	@Produce		json
//	@Param			book_id	path		string					true	"Book ID"
//	@Param			request	body		GenerateAudioRequest	false	"TTS options"
//	@Success		202		{object}	GenerateAudioResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		409		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/generate/audio [post]
func (e *GenerateAudioEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	if err := defra.ValidateID(bookID); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid book_id: %v", err))
		return
	}

	var req GenerateAudioRequest
	if r.Body != nil && r.ContentLength > 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
	}

	ctx := r.Context()

	scheduler := svcctx.SchedulerFrom(ctx)
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}

	configStore := svcctx.ConfigStoreFrom(ctx)
	if configStore == nil {
		writeError(w, http.StatusServiceUnavailable, "config store not initialized")
		return
	}

	// Get TTS config
	builder := jobcfg.NewBuilder(configStore)
	ttsCfg, err := builder.TTSConfig(ctx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to load TTS config: %v", err))
		return
	}

	// Apply request overrides
	if req.Voice != "" {
		ttsCfg.Voice = req.Voice
	}
	if req.Format != "" {
		ttsCfg.Format = req.Format
	}

	if ttsCfg.Format != "" {
		normalized := tts_generate.NormalizeOutputFormat(ttsCfg.Format)
		if !tts_generate.IsStorytellerCompatibleFormat(normalized) {
			writeError(
				w,
				http.StatusBadRequest,
				fmt.Sprintf(
					"unsupported output format %q for storyteller export (supported: %s)",
					ttsCfg.Format,
					strings.Join(tts_generate.SupportedStorytellerFormats(), ", "),
				),
			)
			return
		}
		ttsCfg.Format = normalized
	}

	// If no voice specified, get default voice from database
	if ttsCfg.Voice == "" {
		defraClient := svcctx.DefraClientFrom(ctx)
		if defraClient != nil {
			if defaultVoice, err := voices.GetDefault(ctx, defraClient); err == nil && defaultVoice != nil {
				ttsCfg.Voice = defaultVoice.VoiceID
			}
		}
	}

	// Validate voice is set
	if ttsCfg.Voice == "" {
		writeError(w, http.StatusBadRequest, "no voice specified and no default voice configured. Use 'shelf api voices sync' then 'shelf api voices set-default <voice_id>'")
		return
	}

	if existing := scheduler.GetJobByBookID(bookID); existing != nil && existing.Type() == tts_generate.JobType {
		writeError(w, http.StatusConflict, fmt.Sprintf("audio generation already in progress (job_id: %s)", existing.ID()))
		return
	}

	// Create job
	job, err := tts_generate.NewJob(ctx, ttsCfg, bookID)
	if err != nil {
		switch {
		case errors.Is(err, tts_generate.ErrBookNotFound):
			writeError(w, http.StatusNotFound, err.Error())
		case errors.Is(err, tts_generate.ErrBookNotComplete):
			writeError(w, http.StatusBadRequest, err.Error())
		default:
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create TTS job: %v", err))
		}
		return
	}

	// Submit to scheduler
	if err := scheduler.Submit(ctx, job); err != nil {
		markBookAudioFailedOnSubmit(ctx, bookID, err)
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit job: %v", err))
		return
	}

	// Get chapter count from job
	chapterCount := 0
	if status, err := job.Status(ctx); err == nil {
		if countStr, ok := status["total_chapters"]; ok {
			chapterCount, _ = strconv.Atoi(countStr)
		}
	}

	writeJSON(w, http.StatusAccepted, GenerateAudioResponse{
		JobID:    job.ID(),
		BookID:   bookID,
		Status:   "generating",
		Chapters: chapterCount,
		Provider: ttsCfg.TTSProvider,
	})
}

func (e *GenerateAudioEndpoint) Command(getServerURL func() string) *cobra.Command {
	var voice, format string
	cmd := &cobra.Command{
		Use:   "generate-audio <book_id>",
		Short: "Start TTS audiobook generation",
		Long: `Start TTS audiobook generation for a book.

This generates audio from the book's polished chapter text using
ElevenLabs TTS. Audio is generated paragraph-by-paragraph with request
stitching for prosody continuity, then concatenated into chapter files.

The command submits a job and returns immediately.
Use 'shelf api books audio <book-id>' to check progress.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp GenerateAudioResponse
			if err := client.Post(ctx, fmt.Sprintf("/api/books/%s/generate/audio", bookID), GenerateAudioRequest{
				Voice:  voice,
				Format: format,
			}, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&voice, "voice", "", "Voice ID (optional)")
	cmd.Flags().StringVar(&format, "format", "", "Output format (Storyteller-safe MP3): mp3_44100_128 (default), mp3_22050_32, mp3_44100_32, mp3_44100_64, mp3_44100_96, mp3_44100_192")
	return cmd
}

// GetAudioStatusEndpoint handles GET /api/books/{book_id}/audio.
type GetAudioStatusEndpoint struct{}

func (e *GetAudioStatusEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/audio", e.handler
}

func (e *GetAudioStatusEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get audio status
//	@Description	Get TTS audio generation status and available files
//	@Tags			books,audio
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{object}	AudioStatusResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/audio [get]
func (e *GetAudioStatusEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	// Query BookAudio record
	// Note: Use unique_key (which stores the book's DocID) for lookups,
	// not book_id (which is auto-generated by DefraDB for the relationship).
	bookAudioQuery := fmt.Sprintf(`{
		BookAudio(filter: {unique_key: {_eq: "%s"}}) {
			_docID
			status
			error_message
			provider
			voice
			format
			total_duration_ms
			total_cost_usd
			chapter_count
			segment_count
		}
	}`, bookID)

	bookAudioResp, err := defraClient.Execute(ctx, bookAudioQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query audio status: %v", err))
		return
	}

	records, ok := bookAudioResp.Data["BookAudio"].([]any)
	if !ok || len(records) == 0 {
		writeJSON(w, http.StatusOK, AudioStatusResponse{
			BookID: bookID,
			Status: "not_started",
		})
		return
	}

	data, ok := records[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "invalid audio data")
		return
	}

	resp := AudioStatusResponse{
		BookID:          bookID,
		Status:          getString(data, "status"),
		ErrorMessage:    getString(data, "error_message"),
		Provider:        getString(data, "provider"),
		Voice:           getString(data, "voice"),
		Format:          getString(data, "format"),
		TotalDurationMS: getInt(data, "total_duration_ms"),
		TotalCostUSD:    getFloat(data, "total_cost_usd"),
		ChapterCount:    getInt(data, "chapter_count"),
		SegmentCount:    getInt(data, "segment_count"),
	}

	// Query ChapterAudio records
	chapterQuery := fmt.Sprintf(`{
		ChapterAudio(filter: {book_id: {_eq: "%s"}}) {
			chapter_idx
			duration_ms
			segment_count
			total_cost_usd
			audio_file
		}
	}`, bookID)

	chapterResp, err := defraClient.Execute(ctx, chapterQuery, nil)
	if err == nil {
		if chapters, ok := chapterResp.Data["ChapterAudio"].([]any); ok {
			for _, ch := range chapters {
				chData, ok := ch.(map[string]any)
				if !ok {
					continue
				}
				chapterIdx := getInt(chData, "chapter_idx")
				status := ChapterAudioStatus{
					ChapterIdx:   chapterIdx,
					DurationMS:   getInt(chData, "duration_ms"),
					SegmentCount: getInt(chData, "segment_count"),
					CostUSD:      getFloat(chData, "total_cost_usd"),
					AudioFile:    getString(chData, "audio_file"),
				}
				if status.AudioFile != "" {
					status.DownloadURL = fmt.Sprintf("/api/books/%s/audio/%d/download", bookID, chapterIdx)
				}
				resp.Chapters = append(resp.Chapters, status)
			}
		}
	}

	// Sort chapters by index
	sortChapterStatuses(resp.Chapters)

	writeJSON(w, http.StatusOK, resp)
}

func (e *GetAudioStatusEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "audio <book_id>",
		Short: "Get audio status and files",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp AudioStatusResponse
			if err := client.Get(ctx, fmt.Sprintf("/api/books/%s/audio", bookID), &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// DownloadChapterAudioEndpoint handles GET /api/books/{book_id}/audio/{chapter}/download.
type DownloadChapterAudioEndpoint struct{}

func (e *DownloadChapterAudioEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{book_id}/audio/{chapter}/download", e.handler
}

func (e *DownloadChapterAudioEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Download chapter audio
//	@Description	Download the generated audio file for a chapter
//	@Tags			books,audio
//	@Produce		audio/mpeg
//	@Param			book_id	path		string	true	"Book ID"
//	@Param			chapter	path		int		true	"Chapter index"
//	@Success		200		{file}		file
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/audio/{chapter}/download [get]
func (e *DownloadChapterAudioEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	if err := defra.ValidateID(bookID); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid book_id: %v", err))
		return
	}

	chapterStr := r.PathValue("chapter")
	chapterIdx, err := strconv.Atoi(chapterStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid chapter index")
		return
	}

	ctx := r.Context()
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	// Query ChapterAudio by book_id and chapter_idx
	query := fmt.Sprintf(`{
		ChapterAudio(filter: {book_id: {_eq: "%s"}, chapter_idx: {_eq: %d}}) {
			audio_file
		}
	}`, bookID, chapterIdx)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query chapter audio: %v", err))
		return
	}

	records, ok := resp.Data["ChapterAudio"].([]any)
	if !ok || len(records) == 0 {
		writeError(w, http.StatusNotFound, fmt.Sprintf("no audio record found for chapter %d", chapterIdx))
		return
	}

	data, ok := records[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "invalid chapter audio data")
		return
	}

	audioPath := getString(data, "audio_file")
	if audioPath == "" {
		writeError(w, http.StatusNotFound, fmt.Sprintf("audio file not found for chapter %d", chapterIdx))
		return
	}

	// Verify file exists
	if _, err := os.Stat(audioPath); os.IsNotExist(err) {
		writeError(w, http.StatusNotFound, fmt.Sprintf("audio file missing on disk: %s", audioPath))
		return
	}

	// Determine content type from extension
	ext := filepath.Ext(audioPath)
	contentType := "audio/mpeg"
	switch ext {
	case ".wav":
		contentType = "audio/wav"
	case ".ogg", ".opus":
		contentType = "audio/ogg"
	case ".flac":
		contentType = "audio/flac"
	}

	// Serve file
	filename := filepath.Base(audioPath)
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename="%s"`, filename))
	http.ServeFile(w, r, audioPath)
}

func (e *DownloadChapterAudioEndpoint) Command(getServerURL func() string) *cobra.Command {
	var outputPath string
	cmd := &cobra.Command{
		Use:   "download-audio <book_id> <chapter_idx>",
		Short: "Download chapter audio file",
		Args:  cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]
			chapterIdx := args[1]

			client := api.NewClient(getServerURL())
			data, err := client.GetRaw(ctx, fmt.Sprintf("/api/books/%s/audio/%s/download", bookID, chapterIdx))
			if err != nil {
				return err
			}

			if outputPath == "" {
				outputPath = fmt.Sprintf("chapter_%s.mp3", chapterIdx)
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

func sortChapterStatuses(chapters []ChapterAudioStatus) {
	for i := 0; i < len(chapters)-1; i++ {
		for j := 0; j < len(chapters)-i-1; j++ {
			if chapters[j].ChapterIdx > chapters[j+1].ChapterIdx {
				chapters[j], chapters[j+1] = chapters[j+1], chapters[j]
			}
		}
	}
}

func markBookAudioFailedOnSubmit(ctx context.Context, bookID string, submitErr error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return
	}

	errMsg := submitErr.Error()
	if len(errMsg) > 2000 {
		errMsg = errMsg[:1997] + "..."
	}

	mutation := fmt.Sprintf(`mutation {
		update_BookAudio(filter: {unique_key: {_eq: "%s"}}, input: {
			status: "failed"
			error_message: %q
			completed_at: "%s"
		}) {
			_docID
		}
	}`, bookID, errMsg, time.Now().UTC().Format(time.RFC3339))

	_, _ = defraClient.Execute(ctx, mutation, nil)
}

func getFloat(m map[string]any, key string) float64 {
	if v, ok := m[key].(float64); ok {
		return v
	}
	return 0
}
