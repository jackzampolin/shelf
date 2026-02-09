package tts_generate_openai

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "tts-generate-openai"

const defaultOutputFormat = "mp3"

var (
	// ErrBookNotFound is returned when the requested book cannot be loaded.
	ErrBookNotFound = errors.New("book not found")
	// ErrBookNotComplete is returned when audio generation is requested before processing is complete.
	ErrBookNotComplete = errors.New("book is not complete")
)

var storytellerCompatibleFormats = map[string]struct{}{
	"mp3": {},
}

// Config configures the TTS generation job.
type Config struct {
	// TTS provider settings
	TTSProvider  string // TTS provider name (must be "openai")
	Voice        string // Voice ID (optional)
	Format       string // Output format (mp3)
	Instructions string // Optional instructions for gpt-4o-mini-tts
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.TTSProvider == "" {
		return fmt.Errorf("TTS provider is required")
	}
	if c.TTSProvider != "openai" {
		return fmt.Errorf("invalid TTS provider %q for openai job (expected: openai)", c.TTSProvider)
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
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
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

	return NewJobFromState(state), nil
}

// loadChapters loads chapters with polished text for a book.
func loadChapters(ctx context.Context, client *defra.Client, bookID string) ([]*Chapter, error) {
	query := fmt.Sprintf(`{
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

	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	chapterList, ok := resp.Data["Chapter"].([]any)
	if !ok {
		return nil, nil
	}

	var chapters []*Chapter
	for _, ch := range chapterList {
		chData, ok := ch.(map[string]any)
		if !ok {
			continue
		}

		// Only include chapters with polished text
		polishComplete, _ := chData["polish_complete"].(bool)
		if !polishComplete {
			continue
		}

		polishedText := getString(chData, "polished_text")
		if polishedText == "" {
			continue
		}
		if !resolveAudioInclude(chData) {
			continue
		}

		chapter := &Chapter{
			DocID:        getString(chData, "_docID"),
			EntryID:      getString(chData, "entry_id"),
			Title:        getString(chData, "title"),
			Level:        getInt(chData, "level"),
			LevelName:    getString(chData, "level_name"),
			EntryNumber:  getString(chData, "entry_number"),
			MatterType:   getString(chData, "matter_type"),
			PolishedText: polishedText,
			SortOrder:    getInt(chData, "sort_order"),
		}
		chapters = append(chapters, chapter)
	}

	// Sort by sort_order
	sortChapters(chapters)

	// Assign chapter indices after sorting
	for i, ch := range chapters {
		ch.ChapterIdx = i
	}

	return chapters, nil
}

func resolveAudioInclude(chData map[string]any) bool {
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

// loadBookAudio loads existing BookAudio record if present.
// Uses unique_key (which is set to book_id) for lookups since book_id is auto-generated.
func loadBookAudio(ctx context.Context, client *defra.Client, bookID string) (*BookAudioRecord, error) {
	query := fmt.Sprintf(`{
		BookAudio(filter: {unique_key: {_eq: "%s"}}) {
			_docID
			status
			provider
			model
			voice
			format
			total_duration_ms
			chapter_count
			segment_count
			total_char_count
			total_cost_usd
		}
	}`, bookID)

	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	records, ok := resp.Data["BookAudio"].([]any)
	if !ok || len(records) == 0 {
		return nil, nil
	}

	data, ok := records[0].(map[string]any)
	if !ok {
		return nil, nil
	}

	return &BookAudioRecord{
		ID:            getString(data, "_docID"),
		Status:        getString(data, "status"),
		Provider:      getString(data, "provider"),
		Voice:         getString(data, "voice"),
		Format:        getString(data, "format"),
		TotalDuration: getInt(data, "total_duration_ms"),
		ChapterCount:  getInt(data, "chapter_count"),
		SegmentCount:  getInt(data, "segment_count"),
		TotalChars:    getInt(data, "total_char_count"),
		TotalCost:     getFloat(data, "total_cost_usd"),
	}, nil
}

// loadExistingSegments loads already-generated segments for resume support.
func loadExistingSegments(ctx context.Context, client *defra.Client, bookID string, state *AudioState) error {
	query := fmt.Sprintf(`{
		AudioSegment(filter: {book_id: {_eq: "%s"}}) {
			_docID
			unique_key
			chapter_id
			chapter_idx
			paragraph_idx
			duration_ms
			start_offset_ms
			audio_file
			cost_usd
		}
	}`, bookID)

	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	segments, ok := resp.Data["AudioSegment"].([]any)
	if !ok {
		return nil
	}

	for _, seg := range segments {
		segData, ok := seg.(map[string]any)
		if !ok {
			continue
		}

		chapterDocID := getString(segData, "chapter_id")
		chapterIdx := getInt(segData, "chapter_idx")
		paragraphIdx := getInt(segData, "paragraph_idx")

		// If chapter_id is empty, extract from unique_key
		// unique_key format: "{book_id}:{chapter_docid}:{paragraph_idx}"
		if chapterDocID == "" {
			if uniqueKey := getString(segData, "unique_key"); uniqueKey != "" {
				parts := strings.Split(uniqueKey, ":")
				if len(parts) >= 2 {
					chapterDocID = parts[1]
				}
			}
		}

		// Mark this segment as complete in state
		state.MarkSegmentComplete(chapterDocID, chapterIdx, paragraphIdx, &SegmentResult{
			DocID:         getString(segData, "_docID"),
			DurationMS:    getInt(segData, "duration_ms"),
			StartOffsetMS: getInt(segData, "start_offset_ms"),
			AudioFile:     getString(segData, "audio_file"),
			CostUSD:       getFloat(segData, "cost_usd"),
		})
	}

	return nil
}

// createBookAudioRecord creates a new BookAudio record with "generating" status.
// This is called during NewJob() to ensure the status endpoint can show progress
// immediately, avoiding race conditions with frontend polling.
//
// Note: The `book` relationship is established by DefraDB automatically when
// querying - we use unique_key (set to book_id) for lookups instead of the
// relationship field since `book_id` is auto-generated and cannot be set directly.
func createBookAudioRecord(ctx context.Context, client *defra.Client, state *AudioState) (string, error) {
	format := state.Format
	if format == "" {
		format = defaultOutputFormat
	}

	// Note: Don't set book_id directly - it's auto-generated by DefraDB for the
	// book: Book relationship. Use unique_key for book-specific lookups.
	mutation := fmt.Sprintf(`mutation {
		create_BookAudio(input: {
			unique_key: "%s"
			provider: "%s"
			voice: "%s"
			format: "%s"
			status: "generating"
			started_at: "%s"
			chapter_count: %d
		}) {
			_docID
		}
	}`,
		state.BookID, // unique_key = book_id for lookups
		state.TTSProvider,
		state.Voice,
		format,
		time.Now().UTC().Format(time.RFC3339),
		len(state.Chapters),
	)

	resp, err := client.Execute(ctx, mutation, nil)
	if err != nil {
		return "", err
	}

	// Check for GraphQL errors
	if errMsg := resp.Error(); errMsg != "" {
		return "", fmt.Errorf("graphql error: %s", errMsg)
	}

	// Handle response - could be a single object or array
	if created, ok := resp.Data["create_BookAudio"].(map[string]any); ok {
		return getString(created, "_docID"), nil
	}

	// DefraDB mutations return arrays
	if createdArr, ok := resp.Data["create_BookAudio"].([]any); ok && len(createdArr) > 0 {
		if created, ok := createdArr[0].(map[string]any); ok {
			return getString(created, "_docID"), nil
		}
	}

	return "", fmt.Errorf("no _docID in response: %+v", resp.Data)
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}

// Helper functions

func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getInt(m map[string]any, key string) int {
	if v, ok := m[key].(float64); ok {
		return int(v)
	}
	return 0
}

func getFloat(m map[string]any, key string) float64 {
	if v, ok := m[key].(float64); ok {
		return v
	}
	return 0
}

func sortChapters(chapters []*Chapter) {
	sort.Slice(chapters, func(i, j int) bool {
		return chapters[i].SortOrder < chapters[j].SortOrder
	})
}

// SupportedStorytellerFormats returns output formats known to work with Storyteller export.
func SupportedStorytellerFormats() []string {
	return []string{
		"mp3",
	}
}

// NormalizeOutputFormat normalizes user input to a canonical output format.
func NormalizeOutputFormat(format string) string {
	return normalizeFormat(format, "openai")
}

// NormalizeOutputFormatForProvider normalizes format per provider expectations.
func NormalizeOutputFormatForProvider(provider, format string) string {
	return normalizeFormat(format, provider)
}

// IsStorytellerCompatibleFormat returns true when the format is safe for Storyteller export.
func IsStorytellerCompatibleFormat(format string) bool {
	return isStorytellerCompatibleFormat(normalizeFormat(format, "openai"))
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
		if format == "" || strings.HasPrefix(format, "mp3") {
			return "mp3"
		}
		return format
	default:
		return normalizeFormat(format, "openai")
	}
}
