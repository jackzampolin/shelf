package tts_generate

import (
	"context"
	"fmt"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "tts-generate"

// Config configures the TTS generation job.
type Config struct {
	// TTS provider settings
	TTSProvider string // TTS provider name (e.g., "elevenlabs")
	Voice       string // Voice ID (optional)
	Format      string // Output format (mp3, wav, etc.)
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.TTSProvider == "" {
		return fmt.Errorf("TTS provider is required")
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
		return nil, fmt.Errorf("book not found: %s", bookID)
	}

	bookData, ok := books[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("invalid book data")
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

	// Create job state
	state := &AudioState{
		BookID:      bookID,
		Title:       getString(bookData, "title"),
		Author:      getString(bookData, "author"),
		Chapters:    chapters,
		TTSProvider: cfg.TTSProvider,
		Voice:       cfg.Voice,
		Format:      cfg.Format,
		HomeDir:     homeDir,
	}

	// If there's an existing BookAudio, load segment states
	if existingAudio != nil {
		state.BookAudioID = existingAudio.ID
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

	if logger != nil {
		logger.Info("creating TTS generation job",
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
		format = "mp3"
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
	for i := 0; i < len(chapters)-1; i++ {
		for j := 0; j < len(chapters)-i-1; j++ {
			if chapters[j].SortOrder > chapters[j+1].SortOrder {
				chapters[j], chapters[j+1] = chapters[j+1], chapters[j]
			}
		}
	}
}
