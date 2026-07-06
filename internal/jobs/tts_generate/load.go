package tts_generate

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// loadChapters loads chapters with polished text for a book.
func loadChapters(ctx context.Context, client *defra.Client, bookID string) ([]*Chapter, error) {
	query := fmt.Sprintf(`{
		Chapter(filter: {_bookID: {_eq: "%s"}}) {
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
		AudioSegment(filter: {_bookID: {_eq: "%s"}}) {
			_docID
			unique_key
			_chapterID
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

		chapterDocID := getString(segData, "_chapterID")
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
		add_BookAudio(input: {
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
	if created, ok := resp.Data["add_BookAudio"].(map[string]any); ok {
		return getString(created, "_docID"), nil
	}

	// DefraDB mutations return arrays
	if createdArr, ok := resp.Data["add_BookAudio"].([]any); ok && len(createdArr) > 0 {
		if created, ok := createdArr[0].(map[string]any); ok {
			return getString(created, "_docID"), nil
		}
	}

	return "", fmt.Errorf("no _docID in response: %+v", resp.Data)
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
