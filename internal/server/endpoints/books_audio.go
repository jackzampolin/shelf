package endpoints

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate_openai"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/voices"
)

// GenerateAudioRequest is the request body for starting TTS generation.
type GenerateAudioRequest struct {
	Provider string `json:"provider,omitempty"` // Optional: provider override ("elevenlabs" or "openai")
	Voice    string `json:"voice,omitempty"`    // Optional: voice ID
	Format   string `json:"format,omitempty"`   // Optional: output format (mp3)
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
	provider := strings.ToLower(strings.TrimSpace(ttsCfg.TTSProvider))
	if provider == "" {
		provider = "elevenlabs"
	}

	// Apply provider override from request.
	if req.Provider != "" {
		provider = strings.ToLower(strings.TrimSpace(req.Provider))
	}
	switch provider {
	case "elevenlabs", "openai":
	default:
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unsupported provider %q (supported: elevenlabs, openai)", req.Provider))
		return
	}
	registry := svcctx.RegistryFrom(ctx)
	if registry == nil {
		writeError(w, http.StatusServiceUnavailable, "provider registry not initialized")
		return
	}
	if !registry.HasTTS(provider) {
		if req.Provider != "" {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("provider %q is not configured/enabled", provider))
			return
		}
		writeError(w, http.StatusServiceUnavailable, fmt.Sprintf("default provider %q is not configured/enabled", provider))
		return
	}

	// Apply request overrides
	if req.Voice != "" {
		ttsCfg.Voice = req.Voice
	}
	if req.Format != "" {
		ttsCfg.Format = req.Format
	}
	ttsCfg.TTSProvider = provider

	if ttsCfg.Format != "" {
		switch provider {
		case "openai":
			normalized := tts_generate_openai.NormalizeOutputFormat(ttsCfg.Format)
			if !tts_generate_openai.IsStorytellerCompatibleFormat(normalized) {
				writeError(
					w,
					http.StatusBadRequest,
					fmt.Sprintf(
						"unsupported output format %q for storyteller export (supported: %s)",
						ttsCfg.Format,
						strings.Join(tts_generate_openai.SupportedStorytellerFormats(), ", "),
					),
				)
				return
			}
			ttsCfg.Format = normalized
		default:
			normalized := tts_generate.NormalizeOutputFormatForProvider(provider, ttsCfg.Format)
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
	}

	// If no voice specified, get default voice from database
	if ttsCfg.Voice == "" {
		defraClient := svcctx.DefraClientFrom(ctx)
		if defraClient != nil {
			ttsCfg.Voice = defaultVoiceForProvider(ctx, defraClient, provider)
		}
	}
	if provider == "openai" && ttsCfg.Voice == "" {
		ttsCfg.Voice = "onyx"
	}

	// ElevenLabs requires explicit voice selection.
	if provider == "elevenlabs" && ttsCfg.Voice == "" {
		writeError(w, http.StatusBadRequest, "no voice specified and no default voice configured. Use 'shelf api voices sync' then 'shelf api voices set-default <voice_id>'")
		return
	}

	if existing := scheduler.GetJobByBookID(bookID); existing != nil && isTTSJobType(existing.Type()) {
		writeError(w, http.StatusConflict, fmt.Sprintf("audio generation already in progress (job_id: %s)", existing.ID()))
		return
	}

	// Create job
	var job jobs.Job
	switch provider {
	case "openai":
		openaiCfg, err := builder.OpenAITTSConfig(ctx)
		if err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to load OpenAI TTS config: %v", err))
			return
		}
		openaiCfg.TTSProvider = "openai"
		openaiCfg.Voice = ttsCfg.Voice
		openaiCfg.Format = ttsCfg.Format
		if req.Format != "" {
			openaiCfg.Format = tts_generate_openai.NormalizeOutputFormat(req.Format)
		}
		if req.Voice != "" {
			openaiCfg.Voice = req.Voice
		}
		openaiJob, err := tts_generate_openai.NewJob(ctx, openaiCfg, bookID)
		if err != nil {
			switch {
			case errors.Is(err, tts_generate_openai.ErrBookNotFound):
				writeError(w, http.StatusNotFound, err.Error())
			case errors.Is(err, tts_generate_openai.ErrBookNotComplete):
				writeError(w, http.StatusBadRequest, err.Error())
			default:
				writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create OpenAI TTS job: %v", err))
			}
			return
		}
		job = openaiJob
	default:
		elevenlabsJob, err := tts_generate.NewJob(ctx, ttsCfg, bookID)
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
		job = elevenlabsJob
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
		Provider: provider,
	})
}

func (e *GenerateAudioEndpoint) Command(getServerURL func() string) *cobra.Command {
	var voice, format, provider string
	cmd := &cobra.Command{
		Use:   "generate-audio <book_id>",
		Short: "Start TTS audiobook generation",
		Long: `Start TTS audiobook generation for a book.

This generates audio from the book's polished chapter text using the
configured TTS provider (ElevenLabs or OpenAI).

The command submits a job and returns immediately.
Use 'shelf api books audio <book-id>' to check progress.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp GenerateAudioResponse
			if err := client.Post(ctx, fmt.Sprintf("/api/books/%s/generate/audio", bookID), GenerateAudioRequest{
				Provider: provider,
				Voice:    voice,
				Format:   format,
			}, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&provider, "provider", "", "TTS provider override (elevenlabs or openai)")
	cmd.Flags().StringVar(&voice, "voice", "", "Voice ID (optional)")
	cmd.Flags().StringVar(&format, "format", "", "Output format (Storyteller-safe MP3; use mp3)")
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

	// Query ChapterAudio records (prefer relation field, fall back to unique_key prefix).
	chapterRecords, err := queryChapterAudioRecords(ctx, defraClient, bookID)
	if err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to query chapter audio records", "book_id", bookID, "error", err)
		}
	} else {
		chapterDocIDByIdx := make(map[int]string, len(chapterRecords))
		for _, chData := range chapterRecords {
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
			if chapterDocID := chapterDocIDFromChapterAudioUniqueKey(getString(chData, "unique_key"), bookID); chapterDocID != "" {
				chapterDocIDByIdx[chapterIdx] = chapterDocID
			}
			resp.Chapters = append(resp.Chapters, status)
		}

		// Prefer metrics as source-of-truth for audiobook cost aggregation.
		metricsQuery := svcctx.MetricsQueryFrom(ctx)
		if metricsQuery == nil {
			metricsQuery = metrics.NewQuery(defraClient)
		}
		metricsTotalCost, metricsByChapter, err := audiobookCostsFromMetrics(ctx, metricsQuery, bookID, chapterDocIDByIdx)
		if err != nil {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("failed to query audiobook cost from metrics", "book_id", bookID, "error", err)
			}
		} else {
			resp.TotalCostUSD = metricsTotalCost
			for i := range resp.Chapters {
				if cost, ok := metricsByChapter[resp.Chapters[i].ChapterIdx]; ok {
					resp.Chapters[i].CostUSD = cost
				}
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

	record, err := queryChapterAudioRecordForChapter(ctx, defraClient, bookID, chapterIdx)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to query chapter audio: %v", err))
		return
	}
	if record == nil {
		writeError(w, http.StatusNotFound, fmt.Sprintf("no audio record found for chapter %d", chapterIdx))
		return
	}

	audioPath := getString(record, "audio_file")
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
	sort.Slice(chapters, func(i, j int) bool {
		return chapters[i].ChapterIdx < chapters[j].ChapterIdx
	})
}

func isTTSJobType(jobType string) bool {
	return jobType == tts_generate.JobType || jobType == tts_generate_openai.JobType
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

func defaultVoiceForProvider(ctx context.Context, client *defra.Client, provider string) string {
	defaultVoice, err := voices.GetDefault(ctx, client)
	if err == nil && defaultVoice != nil && strings.EqualFold(defaultVoice.Provider, provider) {
		return defaultVoice.VoiceID
	}

	voiceList, err := voices.List(ctx, client)
	if err != nil {
		return ""
	}
	for _, v := range voiceList {
		if v.IsDefault && strings.EqualFold(v.Provider, provider) {
			return v.VoiceID
		}
	}
	return ""
}

func queryChapterAudioRecords(ctx context.Context, client *defra.Client, bookID string) ([]map[string]any, error) {
	primaryQuery := fmt.Sprintf(`{
		ChapterAudio(filter: {book_id: {_eq: "%s"}}) {
			unique_key
			chapter_idx
			duration_ms
			segment_count
			total_cost_usd
			audio_file
		}
	}`, bookID)
	primaryResp, primaryErr := client.Execute(ctx, primaryQuery, nil)
	if primaryErr == nil {
		records := extractDocMaps(primaryResp.Data, "ChapterAudio")
		if len(records) > 0 {
			return records, nil
		}
	}

	const pageSize = 1000
	var filtered []map[string]any
	for offset := 0; ; offset += pageSize {
		fallbackQuery := fmt.Sprintf(`{
			ChapterAudio(limit: %d, offset: %d, order: {unique_key: ASC}) {
				unique_key
				chapter_idx
				duration_ms
				segment_count
				total_cost_usd
				audio_file
			}
		}`, pageSize, offset)
		fallbackResp, fallbackErr := client.Execute(ctx, fallbackQuery, nil)
		if fallbackErr != nil {
			if primaryErr != nil {
				return nil, primaryErr
			}
			return nil, fallbackErr
		}
		batch := filterChapterAudioByBookID(extractDocMaps(fallbackResp.Data, "ChapterAudio"), bookID)
		filtered = append(filtered, batch...)
		batchRaw := extractDocMaps(fallbackResp.Data, "ChapterAudio")
		if len(batchRaw) < pageSize {
			break
		}
	}
	return filtered, nil
}

func queryChapterAudioRecordForChapter(ctx context.Context, client *defra.Client, bookID string, chapterIdx int) (map[string]any, error) {
	primaryQuery := fmt.Sprintf(`{
		ChapterAudio(filter: {book_id: {_eq: "%s"}, chapter_idx: {_eq: %d}}) {
			unique_key
			chapter_idx
			audio_file
		}
	}`, bookID, chapterIdx)
	primaryResp, primaryErr := client.Execute(ctx, primaryQuery, nil)
	if primaryErr == nil {
		records := extractDocMaps(primaryResp.Data, "ChapterAudio")
		if len(records) > 0 {
			return records[0], nil
		}
	}

	const pageSize = 200
	for offset := 0; ; offset += pageSize {
		fallbackQuery := fmt.Sprintf(`{
			ChapterAudio(filter: {chapter_idx: {_eq: %d}}, limit: %d, offset: %d, order: {unique_key: ASC}) {
				unique_key
				chapter_idx
				audio_file
			}
		}`, chapterIdx, pageSize, offset)
		fallbackResp, fallbackErr := client.Execute(ctx, fallbackQuery, nil)
		if fallbackErr != nil {
			if primaryErr != nil {
				return nil, primaryErr
			}
			return nil, fallbackErr
		}

		batchRaw := extractDocMaps(fallbackResp.Data, "ChapterAudio")
		records := filterChapterAudioByBookID(batchRaw, bookID)
		if len(records) > 0 {
			return records[0], nil
		}
		if len(batchRaw) < pageSize {
			break
		}
	}
	return nil, nil
}

func filterChapterAudioByBookID(records []map[string]any, bookID string) []map[string]any {
	prefix := bookID + ":"
	filtered := make([]map[string]any, 0, len(records))
	for _, rec := range records {
		if strings.HasPrefix(getString(rec, "unique_key"), prefix) {
			filtered = append(filtered, rec)
		}
	}
	return filtered
}

func extractDocMaps(data map[string]any, key string) []map[string]any {
	raw, ok := data[key].([]any)
	if !ok {
		return nil
	}
	out := make([]map[string]any, 0, len(raw))
	for _, item := range raw {
		doc, ok := item.(map[string]any)
		if !ok {
			continue
		}
		out = append(out, doc)
	}
	return out
}

func chapterDocIDFromChapterAudioUniqueKey(uniqueKey, bookID string) string {
	if uniqueKey == "" {
		return ""
	}
	prefix := bookID + ":"
	if !strings.HasPrefix(uniqueKey, prefix) {
		return ""
	}
	rest := strings.TrimPrefix(uniqueKey, prefix)
	if rest == "" {
		return ""
	}
	parts := strings.SplitN(rest, ":", 2)
	return parts[0]
}

func chapterDocIDFromMetricItemKey(itemKey string) string {
	const marker = "_para_"
	idx := strings.Index(itemKey, marker)
	if idx <= 0 {
		return ""
	}
	return itemKey[:idx]
}

func audiobookCostsFromMetrics(ctx context.Context, query *metrics.Query, bookID string, chapterDocIDByIdx map[int]string) (float64, map[int]float64, error) {
	if query == nil {
		return 0, nil, nil
	}

	chapterIdxByDocID := make(map[string]int, len(chapterDocIDByIdx))
	for chapterIdx, chapterDocID := range chapterDocIDByIdx {
		if chapterDocID == "" {
			continue
		}
		chapterIdxByDocID[chapterDocID] = chapterIdx
	}

	stageNames := []string{tts_generate.JobType, tts_generate_openai.JobType}
	costByChapter := make(map[int]float64, len(chapterDocIDByIdx))
	total := 0.0

	for _, stage := range stageNames {
		metricsList, err := query.List(ctx, metrics.Filter{
			BookID: bookID,
			Stage:  stage,
		}, 0)
		if err != nil {
			return 0, nil, err
		}
		for _, metric := range metricsList {
			total += metric.CostUSD
			chapterDocID := chapterDocIDFromMetricItemKey(metric.ItemKey)
			chapterIdx, ok := chapterIdxByDocID[chapterDocID]
			if !ok {
				continue
			}
			costByChapter[chapterIdx] += metric.CostUSD
		}
	}

	return total, costByChapter, nil
}
