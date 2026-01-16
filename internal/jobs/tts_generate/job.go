package tts_generate

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Start initializes the job and returns initial work units.
// For request stitching, we queue only the FIRST incomplete segment of each chapter.
// Subsequent segments are queued in OnComplete with previous_request_ids for prosody continuity.
// This maintains parallel processing across chapters while requiring sequential processing within chapters.
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)

	// Create or update BookAudio record
	if err := j.ensureBookAudioRecord(ctx, defraClient); err != nil {
		return nil, fmt.Errorf("failed to create BookAudio record: %w", err)
	}

	// Ensure audio directories exist
	if err := j.State.HomeDir.EnsureBookAudioDir(j.State.BookID); err != nil {
		return nil, fmt.Errorf("failed to create audio directory: %w", err)
	}

	// Queue only the FIRST incomplete segment of each chapter.
	// This enables request stitching for prosody continuity within chapters
	// while still processing chapters in parallel.
	var units []jobs.WorkUnit

	for _, ch := range j.State.Chapters {
		// Ensure chapter directory exists (use DocID for stable paths)
		if err := j.State.HomeDir.EnsureChapterAudioDir(j.State.BookID, ch.DocID); err != nil {
			return nil, fmt.Errorf("failed to create chapter audio directory: %w", err)
		}

		// Find the first incomplete segment in this chapter
		for paragraphIdx, paragraph := range ch.Paragraphs {
			if j.State.IsSegmentComplete(ch.DocID, paragraphIdx) {
				continue
			}

			// Build previous_request_ids from completed segments in this chapter
			previousRequestIDs := j.getPreviousRequestIDs(ch.DocID)

			unit := j.createTTSWorkUnit(ch, paragraphIdx, paragraph, previousRequestIDs)
			units = append(units, unit)
			break // Only queue the first incomplete segment per chapter
		}
	}

	if logger != nil {
		logger.Info("TTS generation job started",
			"book_id", j.State.BookID,
			"chapters", len(j.State.Chapters),
			"total_segments", j.State.TotalSegments,
			"queued_segments", len(units),
			"provider", j.State.TTSProvider,
			"mode", "sequential_per_chapter")
	}

	return units, nil
}

// OnComplete handles completed work units and generates follow-up work.
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	info, ok := j.Tracker.Get(result.WorkUnitID)
	if !ok {
		return nil, nil // Not our work unit
	}

	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)

	if !result.Success {
		// Handle failure with retry
		if info.RetryCount < 3 {
			if logger != nil {
				logger.Warn("TTS segment failed, retrying",
					"chapter_doc_id", info.ChapterDocID,
					"chapter_idx", info.ChapterIdx,
					"paragraph", info.ParagraphIdx,
					"attempt", info.RetryCount+1,
					"error", result.Error)
			}

			// Find the chapter and paragraph text
			var chapter *Chapter
			var paragraph string
			for _, ch := range j.State.Chapters {
				if ch.DocID == info.ChapterDocID && info.ParagraphIdx < len(ch.Paragraphs) {
					chapter = ch
					paragraph = ch.Paragraphs[info.ParagraphIdx]
					break
				}
			}

			if chapter != nil && paragraph != "" {
				j.Tracker.Remove(result.WorkUnitID)
				previousRequestIDs := j.getPreviousRequestIDs(info.ChapterDocID)
				retryUnit := j.createTTSWorkUnit(chapter, info.ParagraphIdx, paragraph, previousRequestIDs)
				// Update retry count
				retryInfo := info
				retryInfo.RetryCount++
				j.Tracker.Register(retryUnit.ID, retryInfo)
				return []jobs.WorkUnit{retryUnit}, nil
			}
		}

		j.Tracker.Remove(result.WorkUnitID)
		return nil, fmt.Errorf("TTS segment failed after retries: %w", result.Error)
	}

	var newUnits []jobs.WorkUnit

	switch info.UnitType {
	case WorkUnitTypeTTSSegment:
		// TTS segment completed
		ttsResult := result.TTSResult
		if ttsResult == nil {
			j.Tracker.Remove(result.WorkUnitID)
			return nil, fmt.Errorf("TTS result is nil")
		}

		// Save audio file to disk (use DocID for stable paths)
		format := j.State.Format
		if format == "" {
			format = "mp3_44100_128"
		}
		audioPath := j.State.HomeDir.SegmentAudioPath(
			j.State.BookID, info.ChapterDocID, info.ParagraphIdx, format)

		if err := os.WriteFile(audioPath, ttsResult.Audio, 0644); err != nil {
			j.Tracker.Remove(result.WorkUnitID)
			return nil, fmt.Errorf("failed to write audio file: %w", err)
		}

		// Calculate start offset from previous segments
		startOffset := 0
		progress := j.State.ChapterProgress[info.ChapterDocID]
		if progress != nil {
			for i := 0; i < info.ParagraphIdx; i++ {
				if seg, ok := progress.Segments[i]; ok {
					startOffset += seg.DurationMS
				}
			}
		}

		// Create segment result with ElevenLabs request ID for stitching
		segResult := &SegmentResult{
			DurationMS:          ttsResult.DurationMS,
			StartOffsetMS:       startOffset,
			AudioFile:           audioPath,
			CostUSD:             ttsResult.CostUSD,
			CharCount:           ttsResult.CharCount,
			ElevenLabsRequestID: ttsResult.RequestID, // For request stitching
		}

		// Store request ID in chapter progress for subsequent segments
		if ttsResult.RequestID != "" && progress != nil {
			progress.RequestIDSequence = append(progress.RequestIDSequence, ttsResult.RequestID)
		}

		// Get paragraph text for DB record
		var paragraph string
		var chapter *Chapter
		for _, ch := range j.State.Chapters {
			if ch.DocID == info.ChapterDocID {
				chapter = ch
				if info.ParagraphIdx < len(ch.Paragraphs) {
					paragraph = ch.Paragraphs[info.ParagraphIdx]
				}
				break
			}
		}

		// Save to DefraDB
		docID, err := j.saveAudioSegment(ctx, defraClient, sink, info.ChapterDocID, info.ChapterIdx, info.ParagraphIdx, segResult, paragraph)
		if err != nil {
			if logger != nil {
				logger.Error("failed to save audio segment", "error", err)
			}
		} else {
			segResult.DocID = docID
		}

		// Update state
		j.State.MarkSegmentComplete(info.ChapterDocID, info.ChapterIdx, info.ParagraphIdx, segResult)

		if logger != nil {
			logger.Debug("TTS segment complete",
				"chapter_doc_id", info.ChapterDocID,
				"chapter_idx", info.ChapterIdx,
				"paragraph", info.ParagraphIdx,
				"duration_ms", ttsResult.DurationMS,
				"cost", ttsResult.CostUSD,
				"request_id", ttsResult.RequestID)
		}

		// Queue next segment in this chapter (sequential processing for request stitching)
		// OR queue concatenation if chapter is complete
		if j.State.IsChapterComplete(info.ChapterDocID) {
			// All segments done, queue concatenation
			concatUnit := j.createConcatenateWorkUnit(info.ChapterDocID, info.ChapterIdx)
			newUnits = append(newUnits, concatUnit)
		} else if chapter != nil {
			// Queue next segment with previous request IDs for prosody continuity
			nextParagraphIdx := info.ParagraphIdx + 1
			if nextParagraphIdx < len(chapter.Paragraphs) {
				previousRequestIDs := j.getPreviousRequestIDs(info.ChapterDocID)
				nextUnit := j.createTTSWorkUnit(chapter, nextParagraphIdx,
					chapter.Paragraphs[nextParagraphIdx], previousRequestIDs)
				newUnits = append(newUnits, nextUnit)

				if logger != nil && len(previousRequestIDs) > 0 {
					logger.Debug("queuing next segment with request stitching",
						"chapter_doc_id", info.ChapterDocID,
						"next_paragraph", nextParagraphIdx,
						"previous_request_ids", len(previousRequestIDs))
				}
			}
		}

	case WorkUnitTypeConcatenate:
		// Chapter concatenation completed
		if logger != nil {
			logger.Info("chapter audio concatenated",
				"chapter_doc_id", info.ChapterDocID,
				"chapter_idx", info.ChapterIdx)
		}

		// Save ChapterAudio record
		if err := j.saveChapterAudio(ctx, defraClient, sink, info.ChapterDocID, info.ChapterIdx); err != nil {
			if logger != nil {
				logger.Error("failed to save chapter audio record", "error", err)
			}
		}

		// Check if all chapters are done
		allComplete := true
		for _, ch := range j.State.Chapters {
			if !j.State.IsChapterComplete(ch.DocID) {
				allComplete = false
				break
			}
			// Also check that concatenation is done
			progress := j.State.ChapterProgress[ch.DocID]
			if progress == nil || progress.AudioFile == "" {
				allComplete = false
				break
			}
		}

		if allComplete {
			// Update BookAudio status
			if err := j.updateBookAudioComplete(ctx, defraClient, sink); err != nil {
				if logger != nil {
					logger.Error("failed to update BookAudio status", "error", err)
				}
			}
			j.isDone = true

			if logger != nil {
				logger.Info("TTS generation complete",
					"book_id", j.State.BookID,
					"total_duration_ms", j.State.TotalDurationMS,
					"total_cost", j.State.TotalCostUSD)
			}
		}
	}

	j.Tracker.Remove(result.WorkUnitID)
	return newUnits, nil
}

// Status returns the current job status.
func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	chaptersComplete := 0
	for _, ch := range j.State.Chapters {
		if j.State.IsChapterComplete(ch.DocID) {
			chaptersComplete++
		}
	}

	return map[string]string{
		"book_id":            j.State.BookID,
		"provider":           j.State.TTSProvider,
		"total_chapters":     fmt.Sprintf("%d", len(j.State.Chapters)),
		"chapters_complete":  fmt.Sprintf("%d", chaptersComplete),
		"total_segments":     fmt.Sprintf("%d", j.State.TotalSegments),
		"segments_complete":  fmt.Sprintf("%d", j.State.CompletedSegments),
		"total_duration_ms":  fmt.Sprintf("%d", j.State.TotalDurationMS),
		"total_cost_usd":     fmt.Sprintf("%.4f", j.State.TotalCostUSD),
		"done":               fmt.Sprintf("%v", j.isDone),
	}, nil
}

// createTTSWorkUnit creates a TTS work unit for a paragraph.
// previousRequestIDs are ElevenLabs request IDs from prior segments for prosody stitching.
func (j *Job) createTTSWorkUnit(chapter *Chapter, paragraphIdx int, text string, previousRequestIDs []string) jobs.WorkUnit {
	unitID := fmt.Sprintf("tts_%s_%s_%d", j.State.BookID, chapter.DocID, paragraphIdx)

	unit := jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeTTS,
		Provider: j.State.TTSProvider,
		JobID:    j.recordID,
		Priority: 100 - chapter.ChapterIdx, // Earlier chapters have higher priority

		TTSRequest: &jobs.TTSWorkRequest{
			Text:               text,
			Voice:              j.State.Voice,
			Format:             j.State.Format,
			ChapterIdx:         chapter.ChapterIdx,
			ParagraphIdx:       paragraphIdx,
			PreviousRequestIDs: previousRequestIDs, // For ElevenLabs request stitching
		},

		Metrics: &jobs.WorkUnitMetrics{
			BookID:  j.State.BookID,
			Stage:   JobType,
			ItemKey: fmt.Sprintf("%s_para_%d", chapter.DocID, paragraphIdx),
		},
	}

	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType:     WorkUnitTypeTTSSegment,
		ChapterDocID: chapter.DocID,
		ChapterIdx:   chapter.ChapterIdx,
		ParagraphIdx: paragraphIdx,
	})

	return unit
}

// getPreviousRequestIDs returns up to 3 most recent request IDs for a chapter.
// Used for ElevenLabs request stitching to maintain prosody continuity.
func (j *Job) getPreviousRequestIDs(chapterDocID string) []string {
	progress := j.State.ChapterProgress[chapterDocID]
	if progress == nil || len(progress.RequestIDSequence) == 0 {
		return nil
	}

	// ElevenLabs supports up to 3 previous request IDs
	ids := progress.RequestIDSequence
	if len(ids) > 3 {
		ids = ids[len(ids)-3:]
	}

	// Return a copy to avoid mutation
	result := make([]string, len(ids))
	copy(result, ids)
	return result
}

// createConcatenateWorkUnit creates a work unit for concatenating chapter audio.
func (j *Job) createConcatenateWorkUnit(chapterDocID string, chapterIdx int) jobs.WorkUnit {
	unitID := fmt.Sprintf("concat_%s_%s", j.State.BookID, chapterDocID)

	unit := jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeCPU,
		JobID:    j.recordID,
		Priority: 50,

		CPURequest: &jobs.CPUWorkRequest{
			Task: "concatenate_chapter",
			Data: map[string]any{
				"book_id":        j.State.BookID,
				"chapter_doc_id": chapterDocID,
				"chapter_idx":    chapterIdx,
			},
		},

		Metrics: &jobs.WorkUnitMetrics{
			BookID:  j.State.BookID,
			Stage:   JobType,
			ItemKey: fmt.Sprintf("concat_%s", chapterDocID),
		},
	}

	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType:     WorkUnitTypeConcatenate,
		ChapterDocID: chapterDocID,
		ChapterIdx:   chapterIdx,
	})

	return unit
}

// Database operations

func (j *Job) ensureBookAudioRecord(ctx context.Context, client *defra.Client) error {
	// BookAudioID is always set by NewJob() - either from existing record or newly created
	// This just updates the started_at timestamp when the job actually starts running
	if j.State.BookAudioID == "" {
		return fmt.Errorf("BookAudioID not set - this should never happen")
	}

	mutation := fmt.Sprintf(`mutation {
		update_BookAudio(filter: {_docID: {_eq: "%s"}}, input: {
			status: "generating"
			started_at: "%s"
		}) {
			_docID
		}
	}`, j.State.BookAudioID, time.Now().UTC().Format(time.RFC3339))

	_, err := client.Execute(ctx, mutation, nil)
	return err
}

func (j *Job) saveAudioSegment(ctx context.Context, client *defra.Client, sink *defra.Sink, chapterDocID string, chapterIdx, paragraphIdx int, result *SegmentResult, sourceText string) (string, error) {
	uniqueKey := fmt.Sprintf("%s:%s:%d", j.State.BookID, chapterDocID, paragraphIdx)
	format := j.State.Format
	if format == "" {
		format = "mp3_44100_128"
	}

	// Truncate source text for storage (keep first 500 chars for debugging)
	truncatedText := sourceText
	if len(truncatedText) > 500 {
		truncatedText = truncatedText[:500] + "..."
	}

	// Note: chapter_id is auto-generated by DefraDB for chapter: Chapter relationship
	// Use unique_key for lookups instead
	doc := map[string]any{
		"book_id":         j.State.BookID,
		"unique_key":      uniqueKey,
		"chapter_idx":     chapterIdx,
		"paragraph_idx":   paragraphIdx,
		"audio_file":      result.AudioFile,
		"duration_ms":     result.DurationMS,
		"start_offset_ms": result.StartOffsetMS,
		"format":          format,
		"source_text":     truncatedText,
		"char_count":      result.CharCount,
		"cost_usd":        result.CostUSD,
		"created_at":      time.Now().UTC().Format(time.RFC3339),
	}

	// Use sink for async write if available
	if sink != nil {
		sink.Send(defra.WriteOp{
			Op:         defra.OpCreate,
			Collection: "AudioSegment",
			Document:   doc,
		})
		return "", nil
	}

	// Fall back to direct mutation
	// Note: chapter_id is auto-generated by DefraDB for chapter: Chapter relationship
	mutation := fmt.Sprintf(`mutation {
		create_AudioSegment(input: {
			book_id: "%s"
			unique_key: "%s"
			chapter_idx: %d
			paragraph_idx: %d
			audio_file: "%s"
			duration_ms: %d
			start_offset_ms: %d
			format: "%s"
			char_count: %d
			cost_usd: %f
			created_at: "%s"
		}) {
			_docID
		}
	}`,
		j.State.BookID,
		uniqueKey,
		chapterIdx,
		paragraphIdx,
		result.AudioFile,
		result.DurationMS,
		result.StartOffsetMS,
		format,
		result.CharCount,
		result.CostUSD,
		time.Now().UTC().Format(time.RFC3339),
	)

	resp, err := client.Execute(ctx, mutation, nil)
	if err != nil {
		return "", err
	}

	if created, ok := resp.Data["create_AudioSegment"].(map[string]any); ok {
		return getString(created, "_docID"), nil
	}

	return "", nil
}

func (j *Job) saveChapterAudio(ctx context.Context, client *defra.Client, sink *defra.Sink, chapterDocID string, chapterIdx int) error {
	progress := j.State.ChapterProgress[chapterDocID]
	if progress == nil {
		return fmt.Errorf("no progress for chapter %s", chapterDocID)
	}

	uniqueKey := fmt.Sprintf("%s:%s", j.State.BookID, chapterDocID)
	format := j.State.Format
	if format == "" {
		format = "mp3_44100_128"
	}

	// Calculate totals
	totalChars := 0
	for _, seg := range progress.Segments {
		totalChars += seg.CharCount
	}

	// Note: chapter_id is auto-generated by DefraDB for chapter: Chapter relationship
	// Use unique_key for lookups instead
	doc := map[string]any{
		"book_id":          j.State.BookID,
		"unique_key":       uniqueKey,
		"chapter_idx":      chapterIdx,
		"audio_file":       progress.AudioFile,
		"duration_ms":      progress.TotalDurationMS,
		"format":           format,
		"segment_count":    progress.CompletedSegments,
		"total_char_count": totalChars,
		"total_cost_usd":   progress.TotalCostUSD,
		"created_at":       time.Now().UTC().Format(time.RFC3339),
	}

	if sink != nil {
		sink.Send(defra.WriteOp{
			Op:         defra.OpCreate,
			Collection: "ChapterAudio",
			Document:   doc,
		})
		return nil
	}

	// Note: chapter_id is auto-generated by DefraDB for chapter: Chapter relationship
	mutation := fmt.Sprintf(`mutation {
		create_ChapterAudio(input: {
			book_id: "%s"
			unique_key: "%s"
			chapter_idx: %d
			audio_file: "%s"
			duration_ms: %d
			format: "%s"
			segment_count: %d
			total_char_count: %d
			total_cost_usd: %f
			created_at: "%s"
		}) {
			_docID
		}
	}`,
		j.State.BookID,
		uniqueKey,
		chapterIdx,
		progress.AudioFile,
		progress.TotalDurationMS,
		format,
		progress.CompletedSegments,
		totalChars,
		progress.TotalCostUSD,
		time.Now().UTC().Format(time.RFC3339),
	)

	resp, err := client.Execute(ctx, mutation, nil)
	if err != nil {
		return err
	}

	if created, ok := resp.Data["create_ChapterAudio"].(map[string]any); ok {
		progress.ChapterAudioID = getString(created, "_docID")
	}

	return nil
}

func (j *Job) updateBookAudioComplete(ctx context.Context, client *defra.Client, sink *defra.Sink) error {
	if j.State.BookAudioID == "" {
		return nil
	}

	doc := map[string]any{
		"status":           "complete",
		"completed_at":     time.Now().UTC().Format(time.RFC3339),
		"total_duration_ms": j.State.TotalDurationMS,
		"segment_count":    j.State.CompletedSegments,
		"total_cost_usd":   j.State.TotalCostUSD,
	}

	if sink != nil {
		sink.Send(defra.WriteOp{
			Op:         defra.OpUpdate,
			Collection: "BookAudio",
			DocID:      j.State.BookAudioID,
			Document:   doc,
		})
		return nil
	}

	mutation := fmt.Sprintf(`mutation {
		update_BookAudio(filter: {_docID: {_eq: "%s"}}, input: {
			status: "complete"
			completed_at: "%s"
			total_duration_ms: %d
			segment_count: %d
			total_cost_usd: %f
		}) {
			_docID
		}
	}`,
		j.State.BookAudioID,
		time.Now().UTC().Format(time.RFC3339),
		j.State.TotalDurationMS,
		j.State.CompletedSegments,
		j.State.TotalCostUSD,
	)

	_, err := client.Execute(ctx, mutation, nil)
	return err
}

// ConcatenateChapterAudio concatenates segment audio files into chapter audio.
// This is called by the CPU worker pool when processing concatenation work units.
func ConcatenateChapterAudio(ctx context.Context, bookID, chapterDocID string, homeDir *home.Dir, format string) (string, error) {
	if format == "" {
		format = "mp3_44100_128"
	}

	chapterDir := homeDir.ChapterAudioDir(bookID, chapterDocID)
	outputPath := homeDir.ChapterAudioPath(bookID, chapterDocID, format)

	// Find all segment files in order
	entries, err := os.ReadDir(chapterDir)
	if err != nil {
		return "", fmt.Errorf("failed to read chapter directory: %w", err)
	}

	var segmentFiles []string
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		name := entry.Name()
		if filepath.Ext(name) == "."+format {
			segmentFiles = append(segmentFiles, filepath.Join(chapterDir, name))
		}
	}

	if len(segmentFiles) == 0 {
		return "", fmt.Errorf("no segment files found in %s", chapterDir)
	}

	// Sort segment files by name (segment_0000, segment_0001, etc.)
	sortStrings(segmentFiles)

	// Use ffmpeg to concatenate
	if err := concatenateWithFFmpeg(ctx, segmentFiles, outputPath); err != nil {
		return "", fmt.Errorf("ffmpeg concatenation failed: %w", err)
	}

	return outputPath, nil
}

func sortStrings(strs []string) {
	for i := 0; i < len(strs)-1; i++ {
		for j := 0; j < len(strs)-i-1; j++ {
			if strs[j] > strs[j+1] {
				strs[j], strs[j+1] = strs[j+1], strs[j]
			}
		}
	}
}
