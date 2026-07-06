package tts_generate

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Persisted job-type strings. These identify jobs in DefraDB job records and
// must never change; each pins a provider strategy (see strategyForJobType).
const (
	JobTypeElevenLabs = "tts-generate"        // persisted in DefraDB job records
	JobTypeOpenAI     = "tts-generate-openai" // persisted in DefraDB job records
)

const defaultOutputFormat = "mp3_44100_128"

var (
	// ErrBookNotFound is returned when the requested book cannot be loaded.
	ErrBookNotFound = errors.New("book not found")
	// ErrBookNotComplete is returned when audio generation is requested before processing is complete.
	ErrBookNotComplete = errors.New("book is not complete")
)

var storytellerCompatibleFormats = map[string]struct{}{
	"mp3":           {},
	"mp3_22050_32":  {},
	"mp3_44100_32":  {},
	"mp3_44100_64":  {},
	"mp3_44100_96":  {},
	"mp3_44100_128": {},
	"mp3_44100_192": {},
}

// Config configures the TTS generation job.
type Config struct {
	// TTS provider settings
	TTSProvider  string // TTS provider name (e.g., "elevenlabs")
	Voice        string // Voice ID (optional)
	Format       string // Output format (mp3, wav, etc.)
	Instructions string // Optional instructions for gpt-4o-mini-tts (OpenAI only)
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.TTSProvider == "" {
		return fmt.Errorf("TTS provider is required")
	}
	if c.Format != "" {
		normalized := normalizeFormat(c.Format, c.TTSProvider)
		if !isStorytellerCompatibleFormat(normalized) {
			return fmt.Errorf(
				"unsupported output format %q for storyteller export (supported: %s)",
				c.Format,
				strings.Join(SupportedStorytellerFormats(), ", "),
			)
		}
	}
	return nil
}

// NewJob creates a new TTS generation job for the given book.
// jobType is the persisted job-type string (JobTypeElevenLabs or JobTypeOpenAI)
// and pins the provider strategy for the life of the job.
func NewJob(ctx context.Context, jobType string, cfg Config, bookID string) (*Job, error) {
	strat, provider, err := resolvePairing(jobType, cfg.TTSProvider)
	if err != nil {
		return nil, err
	}
	cfg.TTSProvider = provider
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	// Load book metadata
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			_docID
			title
			author
			status
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	books, ok := bookResp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return nil, fmt.Errorf("%w: %s", ErrBookNotFound, bookID)
	}

	bookData, ok := books[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("invalid book data")
	}
	bookStatus := getString(bookData, "status")
	if bookStatus != "complete" {
		return nil, fmt.Errorf("%w (status: %s)", ErrBookNotComplete, bookStatus)
	}

	// Load chapters with polished text
	chapters, err := loadChapters(ctx, defraClient, bookID)
	if err != nil {
		return nil, fmt.Errorf("failed to load chapters: %w", err)
	}

	if len(chapters) == 0 {
		return nil, fmt.Errorf("no chapters with polished text found")
	}

	// Check for existing BookAudio record
	existingAudio, err := loadBookAudio(ctx, defraClient, bookID)
	if err != nil {
		return nil, fmt.Errorf("failed to check existing audio: %w", err)
	}

	// Resume cross-check: the persisted BookAudio provider must match the
	// strategy pinned by this job type. Failing here beats resuming an
	// openai-generated book with elevenlabs orchestration (or vice versa).
	if existingAudio != nil && existingAudio.Provider != "" && existingAudio.Provider != strat.Provider() {
		return nil, fmt.Errorf(
			"existing BookAudio for book %s was generated with provider %q; job type %q is pinned to provider %q — delete the BookAudio record or start the matching job type",
			bookID, existingAudio.Provider, jobType, strat.Provider())
	}

	// Apply explicit format override only when provided.
	// If omitted, we preserve existing BookAudio format on resume.
	stateFormat := ""
	if cfg.Format != "" {
		stateFormat = normalizeFormat(cfg.Format, cfg.TTSProvider)
	}

	// Create job state
	state := &AudioState{
		BookID:          bookID,
		Title:           getString(bookData, "title"),
		Author:          getString(bookData, "author"),
		Chapters:        chapters,
		TTSProvider:     cfg.TTSProvider,
		Voice:           cfg.Voice,
		Format:          stateFormat,
		Instructions:    cfg.Instructions,
		HomeDir:         homeDir,
		ChapterProgress: make(map[string]*ChapterProgress),
	}

	// If there's an existing BookAudio, load segment states and restore config
	if existingAudio != nil {
		state.BookAudioID = existingAudio.ID
		// Restore voice and format from existing record if not provided in config
		// This is critical for job resume - the voice must be persisted
		if state.Voice == "" {
			state.Voice = existingAudio.Voice
		}
		if state.Format == "" {
			state.Format = normalizeFormat(existingAudio.Format, state.TTSProvider)
		}
		if err := loadExistingSegments(ctx, defraClient, bookID, state); err != nil {
			return nil, fmt.Errorf("failed to load existing segments: %w", err)
		}
	} else {
		// Create BookAudio record immediately so status endpoint can show "generating"
		// This must happen before the job is submitted to avoid race with frontend polling
		bookAudioID, err := createBookAudioRecord(ctx, defraClient, state)
		if err != nil {
			return nil, fmt.Errorf("failed to create BookAudio record: %w", err)
		}
		state.BookAudioID = bookAudioID
	}
	if state.Format == "" {
		state.Format = normalizeFormat("", state.TTSProvider)
	}
	if !isStorytellerCompatibleFormat(state.Format) {
		return nil, fmt.Errorf(
			"output format %q is not storyteller-compatible (supported: %s)",
			state.Format,
			strings.Join(SupportedStorytellerFormats(), ", "),
		)
	}

	if logger != nil {
		logger.Debug("creating TTS generation job",
			"book_id", bookID,
			"chapters", len(chapters),
			"provider", cfg.TTSProvider)
	}

	return NewJobFromState(jobType, state)
}

// SupportedStorytellerFormats returns output formats known to work with Storyteller export.
func SupportedStorytellerFormats() []string {
	return []string{
		"mp3",
		"mp3_22050_32",
		"mp3_44100_32",
		"mp3_44100_64",
		"mp3_44100_96",
		"mp3_44100_128",
		"mp3_44100_192",
	}
}

// SupportedStorytellerFormatsForProvider returns the storyteller-compatible
// output formats for a specific TTS provider. OpenAI TTS emits mp3 only.
func SupportedStorytellerFormatsForProvider(provider string) []string {
	if provider == "openai" {
		return []string{"mp3"}
	}
	return SupportedStorytellerFormats()
}

// IsStorytellerCompatibleFormatForProvider reports whether the format (after
// provider-specific normalization) is safe for Storyteller export.
func IsStorytellerCompatibleFormatForProvider(provider, format string) bool {
	normalized := normalizeFormat(format, provider)
	if provider == "openai" {
		return normalized == "mp3"
	}
	return isStorytellerCompatibleFormat(normalized)
}

// NormalizeOutputFormat normalizes user input to a canonical output format.
func NormalizeOutputFormat(format string) string {
	return normalizeFormat(format, "elevenlabs")
}

// NormalizeOutputFormatForProvider normalizes format per provider expectations.
func NormalizeOutputFormatForProvider(provider, format string) string {
	return normalizeFormat(format, provider)
}

// IsStorytellerCompatibleFormat returns true when the format is safe for Storyteller export.
func IsStorytellerCompatibleFormat(format string) bool {
	return isStorytellerCompatibleFormat(normalizeFormat(format, "elevenlabs"))
}

func isStorytellerCompatibleFormat(format string) bool {
	_, ok := storytellerCompatibleFormats[format]
	return ok
}

// normalizeFormat ensures the format is provider-compatible.
// Storyteller export currently uses MP3-only output.
func normalizeFormat(format, provider string) string {
	format = strings.ToLower(strings.TrimSpace(format))
	switch provider {
	case "openai":
		// OpenAI TTS supports mp3-only output; collapse all mp3 variants.
		if format == "" || strings.HasPrefix(format, "mp3") {
			return "mp3"
		}
		return format
	default:
		// ElevenLabs-specific normalization.
		if format == "" || format == "mp3" {
			return defaultOutputFormat
		}
		return format
	}
}
