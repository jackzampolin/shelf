package endpoints

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/tts_generate"
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
		provider = "openai"
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
			normalized := tts_generate.NormalizeOutputFormatForProvider("openai", ttsCfg.Format)
			if !tts_generate.IsStorytellerCompatibleFormatForProvider("openai", ttsCfg.Format) {
				writeError(
					w,
					http.StatusBadRequest,
					fmt.Sprintf(
						"unsupported output format %q for storyteller export (supported: %s)",
						ttsCfg.Format,
						strings.Join(tts_generate.SupportedStorytellerFormatsForProvider("openai"), ", "),
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
			openaiCfg.Format = tts_generate.NormalizeOutputFormatForProvider("openai", req.Format)
		}
		if req.Voice != "" {
			openaiCfg.Voice = req.Voice
		}
		openaiJob, err := tts_generate.NewJob(ctx, tts_generate.JobTypeOpenAI, openaiCfg, bookID)
		if err != nil {
			switch {
			case errors.Is(err, tts_generate.ErrBookNotFound):
				writeError(w, http.StatusNotFound, err.Error())
			case errors.Is(err, tts_generate.ErrBookNotComplete):
				writeError(w, http.StatusBadRequest, err.Error())
			default:
				writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create OpenAI TTS job: %v", err))
			}
			return
		}
		job = openaiJob
	default:
		elevenlabsJob, err := tts_generate.NewJob(ctx, tts_generate.JobTypeElevenLabs, ttsCfg, bookID)
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

// Helper functions

func isTTSJobType(jobType string) bool {
	return jobType == tts_generate.JobTypeElevenLabs || jobType == tts_generate.JobTypeOpenAI
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
