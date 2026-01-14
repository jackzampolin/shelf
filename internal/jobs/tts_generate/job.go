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

	// Generate work units for all chapters and paragraphs
	var units []jobs.WorkUnit

	for _, ch := range j.State.Chapters {
		// Ensure chapter directory exists
		if err := j.State.HomeDir.EnsureChapterAudioDir(j.State.BookID, ch.ChapterIdx); err != nil {
			return nil, fmt.Errorf("failed to create chapter audio directory: %w", err)
		}

		for paragraphIdx, paragraph := range ch.Paragraphs {
			// Skip already-completed segments
			if j.State.IsSegmentComplete(ch.ChapterIdx, paragraphIdx) {
				continue
			}

			unit := j.createTTSWorkUnit(ch.ChapterIdx, paragraphIdx, paragraph)
			units = append(units, unit)
		}
	}

	if logger != nil {
		logger.Info("TTS generation job started",
			"book_id", j.State.BookID,
			"chapters", len(j.State.Chapters),
			"total_segments", j.State.TotalSegments,
			"pending_segments", len(units),
			"provider", j.State.TTSProvider)
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
					"chapter", info.ChapterIdx,
					"paragraph", info.ParagraphIdx,
					"attempt", info.RetryCount+1,
					"error", result.Error)
			}

			// Find the paragraph text
			var paragraph string
			for _, ch := range j.State.Chapters {
				if ch.ChapterIdx == info.ChapterIdx && info.ParagraphIdx < len(ch.Paragraphs) {
					paragraph = ch.Paragraphs[info.ParagraphIdx]
					break
				}
			}

			if paragraph != "" {
				j.Tracker.Remove(result.WorkUnitID)
				retryUnit := j.createTTSWorkUnit(info.ChapterIdx, info.ParagraphIdx, paragraph)
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

		// Save audio file to disk
		format := j.State.Format
		if format == "" {
			format = "mp3"
		}
		audioPath := j.State.HomeDir.SegmentAudioPath(
			j.State.BookID, info.ChapterIdx, info.ParagraphIdx, format)

		if err := os.WriteFile(audioPath, ttsResult.Audio, 0644); err != nil {
			j.Tracker.Remove(result.WorkUnitID)
			return nil, fmt.Errorf("failed to write audio file: %w", err)
		}

		// Calculate start offset from previous segments
		startOffset := 0
		progress := j.State.ChapterProgress[info.ChapterIdx]
		if progress != nil {
			for i := 0; i < info.ParagraphIdx; i++ {
				if seg, ok := progress.Segments[i]; ok {
					startOffset += seg.DurationMS
				}
			}
		}

		// Create segment result
		segResult := &SegmentResult{
			DurationMS:    ttsResult.DurationMS,
			StartOffsetMS: startOffset,
			AudioFile:     audioPath,
			CostUSD:       ttsResult.CostUSD,
			CharCount:     ttsResult.CharCount,
		}

		// Get paragraph text for DB record
		var paragraph string
		for _, ch := range j.State.Chapters {
			if ch.ChapterIdx == info.ChapterIdx && info.ParagraphIdx < len(ch.Paragraphs) {
				paragraph = ch.Paragraphs[info.ParagraphIdx]
				break
			}
		}

		// Save to DefraDB
		docID, err := j.saveAudioSegment(ctx, defraClient, sink, info.ChapterIdx, info.ParagraphIdx, segResult, paragraph)
		if err != nil {
			if logger != nil {
				logger.Error("failed to save audio segment", "error", err)
			}
		} else {
			segResult.DocID = docID
		}

		// Update state
		j.State.MarkSegmentComplete(info.ChapterIdx, info.ParagraphIdx, segResult)

		if logger != nil {
			logger.Debug("TTS segment complete",
				"chapter", info.ChapterIdx,
				"paragraph", info.ParagraphIdx,
				"duration_ms", ttsResult.DurationMS,
				"cost", ttsResult.CostUSD)
		}

		// Check if chapter is now complete
		if j.State.IsChapterComplete(info.ChapterIdx) {
			// Queue concatenation work unit
			concatUnit := j.createConcatenateWorkUnit(info.ChapterIdx)
			newUnits = append(newUnits, concatUnit)
		}

	case WorkUnitTypeConcatenate:
		// Chapter concatenation completed
		if logger != nil {
			logger.Info("chapter audio concatenated",
				"chapter", info.ChapterIdx)
		}

		// Save ChapterAudio record
		if err := j.saveChapterAudio(ctx, defraClient, sink, info.ChapterIdx); err != nil {
			if logger != nil {
				logger.Error("failed to save chapter audio record", "error", err)
			}
		}

		// Check if all chapters are done
		allComplete := true
		for _, ch := range j.State.Chapters {
			if !j.State.IsChapterComplete(ch.ChapterIdx) {
				allComplete = false
				break
			}
			// Also check that concatenation is done
			progress := j.State.ChapterProgress[ch.ChapterIdx]
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
		if j.State.IsChapterComplete(ch.ChapterIdx) {
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
func (j *Job) createTTSWorkUnit(chapterIdx, paragraphIdx int, text string) jobs.WorkUnit {
	unitID := fmt.Sprintf("tts_%s_%d_%d", j.State.BookID, chapterIdx, paragraphIdx)

	unit := jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeTTS,
		Provider: j.State.TTSProvider,
		JobID:    j.recordID,
		Priority: 100 - chapterIdx, // Earlier chapters have higher priority

		TTSRequest: &jobs.TTSWorkRequest{
			Text:         text,
			Voice:        j.State.Voice,
			Format:       j.State.Format,
			ChapterIdx:   chapterIdx,
			ParagraphIdx: paragraphIdx,
		},

		Metrics: &jobs.WorkUnitMetrics{
			BookID:  j.State.BookID,
			Stage:   JobType,
			ItemKey: fmt.Sprintf("chapter_%d_para_%d", chapterIdx, paragraphIdx),
		},
	}

	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType:     WorkUnitTypeTTSSegment,
		ChapterIdx:   chapterIdx,
		ParagraphIdx: paragraphIdx,
	})

	return unit
}

// createConcatenateWorkUnit creates a work unit for concatenating chapter audio.
func (j *Job) createConcatenateWorkUnit(chapterIdx int) jobs.WorkUnit {
	unitID := fmt.Sprintf("concat_%s_%d", j.State.BookID, chapterIdx)

	unit := jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeCPU,
		JobID:    j.recordID,
		Priority: 50,

		CPURequest: &jobs.CPUWorkRequest{
			Task: "concatenate_chapter",
			Data: map[string]any{
				"book_id":     j.State.BookID,
				"chapter_idx": chapterIdx,
			},
		},

		Metrics: &jobs.WorkUnitMetrics{
			BookID:  j.State.BookID,
			Stage:   JobType,
			ItemKey: fmt.Sprintf("concat_chapter_%d", chapterIdx),
		},
	}

	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeConcatenate,
		ChapterIdx: chapterIdx,
	})

	return unit
}

// Database operations

func (j *Job) ensureBookAudioRecord(ctx context.Context, client *defra.Client) error {
	if j.State.BookAudioID != "" {
		// Update existing record
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

	// Create new record
	format := j.State.Format
	if format == "" {
		format = "mp3"
	}

	mutation := fmt.Sprintf(`mutation {
		create_BookAudio(input: {
			book_id: "%s"
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
		j.State.BookID,
		j.State.BookID,
		j.State.TTSProvider,
		j.State.Voice,
		format,
		time.Now().UTC().Format(time.RFC3339),
		len(j.State.Chapters),
	)

	resp, err := client.Execute(ctx, mutation, nil)
	if err != nil {
		return err
	}

	if created, ok := resp.Data["create_BookAudio"].(map[string]any); ok {
		j.State.BookAudioID = getString(created, "_docID")
	}

	return nil
}

func (j *Job) saveAudioSegment(ctx context.Context, client *defra.Client, sink *defra.Sink, chapterIdx, paragraphIdx int, result *SegmentResult, sourceText string) (string, error) {
	// Find chapter DocID
	var chapterDocID string
	for _, ch := range j.State.Chapters {
		if ch.ChapterIdx == chapterIdx {
			chapterDocID = ch.DocID
			break
		}
	}

	uniqueKey := fmt.Sprintf("%s:%d:%d", j.State.BookID, chapterIdx, paragraphIdx)
	format := j.State.Format
	if format == "" {
		format = "mp3"
	}

	// Truncate source text for storage (keep first 500 chars for debugging)
	truncatedText := sourceText
	if len(truncatedText) > 500 {
		truncatedText = truncatedText[:500] + "..."
	}

	doc := map[string]any{
		"book_id":          j.State.BookID,
		"chapter_id":       chapterDocID,
		"unique_key":       uniqueKey,
		"chapter_idx":      chapterIdx,
		"paragraph_idx":    paragraphIdx,
		"audio_file":       result.AudioFile,
		"duration_ms":      result.DurationMS,
		"start_offset_ms":  result.StartOffsetMS,
		"format":           format,
		"source_text":      truncatedText,
		"char_count":       result.CharCount,
		"cost_usd":         result.CostUSD,
		"created_at":       time.Now().UTC().Format(time.RFC3339),
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
	mutation := fmt.Sprintf(`mutation {
		create_AudioSegment(input: {
			book_id: "%s"
			chapter_id: "%s"
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
		chapterDocID,
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

func (j *Job) saveChapterAudio(ctx context.Context, client *defra.Client, sink *defra.Sink, chapterIdx int) error {
	progress := j.State.ChapterProgress[chapterIdx]
	if progress == nil {
		return fmt.Errorf("no progress for chapter %d", chapterIdx)
	}

	// Find chapter info
	var chapterDocID string
	for _, ch := range j.State.Chapters {
		if ch.ChapterIdx == chapterIdx {
			chapterDocID = ch.DocID
			break
		}
	}

	uniqueKey := fmt.Sprintf("%s:%d", j.State.BookID, chapterIdx)
	format := j.State.Format
	if format == "" {
		format = "mp3"
	}

	// Calculate totals
	totalChars := 0
	for _, seg := range progress.Segments {
		totalChars += seg.CharCount
	}

	doc := map[string]any{
		"book_id":          j.State.BookID,
		"chapter_id":       chapterDocID,
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

	mutation := fmt.Sprintf(`mutation {
		create_ChapterAudio(input: {
			book_id: "%s"
			chapter_id: "%s"
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
		chapterDocID,
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
func ConcatenateChapterAudio(ctx context.Context, bookID string, chapterIdx int, homeDir *home.Dir, format string) (string, error) {
	if format == "" {
		format = "mp3"
	}

	chapterDir := homeDir.ChapterAudioDir(bookID, chapterIdx)
	outputPath := homeDir.ChapterAudioPath(bookID, chapterIdx, format)

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
