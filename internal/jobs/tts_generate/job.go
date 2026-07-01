package tts_generate

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Start initializes the job and returns initial work units.
// The queueing model is provider-specific: ElevenLabs queues only the FIRST
// incomplete segment of each chapter (sequential stitching); OpenAI queues all
// incomplete segments in parallel. See providerStrategy.InitialWorkUnits.
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)

	// Create or update BookAudio record
	if err := j.ensureBookAudioRecord(ctx, defraClient); err != nil {
		startErr := fmt.Errorf("failed to create BookAudio record: %w", err)
		j.markBookAudioFailed(ctx, defraClient, startErr)
		return nil, startErr
	}

	// Ensure audio directories exist
	if err := j.State.HomeDir.EnsureBookAudioDir(j.State.BookID); err != nil {
		startErr := fmt.Errorf("failed to create audio directory: %w", err)
		j.markBookAudioFailed(ctx, defraClient, startErr)
		return nil, startErr
	}

	for _, ch := range j.State.Chapters {
		// Ensure chapter directory exists (use DocID for stable paths)
		if err := j.State.HomeDir.EnsureChapterAudioDir(j.State.BookID, ch.DocID); err != nil {
			startErr := fmt.Errorf("failed to create chapter audio directory: %w", err)
			j.markBookAudioFailed(ctx, defraClient, startErr)
			return nil, startErr
		}
	}

	// Delegate queueing to the provider strategy.
	units := j.strategy.InitialWorkUnits(j)

	if logger != nil {
		logger.Info("TTS generation job started",
			"book_id", j.State.BookID,
			"chapters", len(j.State.Chapters),
			"total_segments", j.State.TotalSegments,
			"queued_segments", len(units),
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

	if !result.Success {
		// Retry only TTS segment failures.
		if info.UnitType == WorkUnitTypeTTSSegment && info.RetryCount < 3 {
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
				if shouldDisableRequestStitching(result.Error) {
					previousRequestIDs = nil
					j.clearRequestIDSequence(info.ChapterDocID)
					if logger != nil {
						logger.Warn("retrying segment without request stitching",
							"chapter_doc_id", info.ChapterDocID,
							"paragraph", info.ParagraphIdx,
							"error", result.Error)
					}
				}
				retryUnit := j.createTTSWorkUnit(chapter, info.ParagraphIdx, paragraph, previousRequestIDs)
				// Update retry count
				retryInfo := info
				retryInfo.RetryCount++
				j.Tracker.Register(retryUnit.ID, retryInfo)
				return []jobs.WorkUnit{retryUnit}, nil
			}
		}

		j.Tracker.Remove(result.WorkUnitID)

		cause := result.Error
		if cause == nil {
			cause = fmt.Errorf("unknown failure")
		}

		var failErr error
		switch info.UnitType {
		case WorkUnitTypeTTSSegment:
			failErr = fmt.Errorf("TTS segment failed after retries: %w", cause)
		case WorkUnitTypeConcatenate:
			failErr = fmt.Errorf("chapter concatenation failed (chapter_doc_id=%s, chapter_idx=%d): %w", info.ChapterDocID, info.ChapterIdx, cause)
		default:
			failErr = fmt.Errorf("work unit failed (type=%s): %w", info.UnitType, cause)
		}
		j.markBookAudioFailed(ctx, defraClient, failErr)
		return nil, failErr
	}

	var newUnits []jobs.WorkUnit

	switch info.UnitType {
	case WorkUnitTypeTTSSegment:
		// TTS segment completed - delegate persistence and follow-up
		// queueing to the provider strategy.
		units, err := j.strategy.OnSegmentComplete(ctx, j, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case WorkUnitTypeConcatenate:
		// Chapter concatenation completed
		// Extract output_path from CPU result and update progress
		outputPath := ""
		if result.CPUResult != nil && result.CPUResult.Data != nil {
			if dataMap, ok := result.CPUResult.Data.(map[string]any); ok {
				if path, ok := dataMap["output_path"].(string); ok {
					outputPath = path
				}
			}
		}

		progress := j.State.ChapterProgress[info.ChapterDocID]
		if progress != nil && outputPath != "" {
			progress.AudioFile = outputPath
		}

		if logger != nil {
			logger.Debug("chapter audio concatenated",
				"chapter_doc_id", info.ChapterDocID,
				"chapter_idx", info.ChapterIdx,
				"output_path", outputPath)
		}

		// Save ChapterAudio record (now has AudioFile set)
		if err := j.saveChapterAudio(ctx, defraClient, info.ChapterDocID, info.ChapterIdx); err != nil {
			j.Tracker.Remove(result.WorkUnitID)
			persistErr := fmt.Errorf("failed to save chapter audio record: %w", err)
			j.markBookAudioFailed(ctx, defraClient, persistErr)
			return nil, persistErr
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
			if err := j.updateBookAudioComplete(ctx, defraClient); err != nil {
				j.Tracker.Remove(result.WorkUnitID)
				persistErr := fmt.Errorf("failed to update BookAudio status: %w", err)
				j.markBookAudioFailed(ctx, defraClient, persistErr)
				return nil, persistErr
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
		"book_id":           j.State.BookID,
		"provider":          j.State.TTSProvider,
		"total_chapters":    fmt.Sprintf("%d", len(j.State.Chapters)),
		"chapters_complete": fmt.Sprintf("%d", chaptersComplete),
		"total_segments":    fmt.Sprintf("%d", j.State.TotalSegments),
		"segments_complete": fmt.Sprintf("%d", j.State.CompletedSegments),
		"total_duration_ms": fmt.Sprintf("%d", j.State.TotalDurationMS),
		"total_cost_usd":    fmt.Sprintf("%.4f", j.State.TotalCostUSD),
		"done":              fmt.Sprintf("%v", j.isDone),
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
			Stage:   j.jobType,
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

// createConcatenateWorkUnit creates a work unit for concatenating chapter audio.
func (j *Job) createConcatenateWorkUnit(chapterDocID string, chapterIdx int) jobs.WorkUnit {
	unitID := fmt.Sprintf("concat_%s_%s", j.State.BookID, chapterDocID)

	unit := jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeCPU,
		JobID:    j.recordID,
		Priority: 50,

		CPURequest: &jobs.CPUWorkRequest{
			Task: j.strategy.ConcatTaskName(),
			Data: map[string]any{
				"book_id":        j.State.BookID,
				"chapter_doc_id": chapterDocID,
				"chapter_idx":    chapterIdx,
				"format":         j.State.Format,
			},
		},

		Metrics: &jobs.WorkUnitMetrics{
			BookID:  j.State.BookID,
			Stage:   j.jobType,
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
