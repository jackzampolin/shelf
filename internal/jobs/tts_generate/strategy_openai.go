package tts_generate

import (
	"context"
	"fmt"
	"os"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// openAIStrategy implements the parallel all-segments orchestration for
// OpenAI TTS. OpenAI has no request stitching, so all segments are queued in
// parallel and deterministic offsets are recalculated when a chapter completes.
type openAIStrategy struct{}

func (openAIStrategy) Provider() string       { return "openai" }
func (openAIStrategy) JobType() string        { return JobTypeOpenAI }
func (openAIStrategy) ConcatTaskName() string { return TaskConcatenateChapterOpenAI }
func (openAIStrategy) DefaultFormat() string  { return "mp3" }

func (openAIStrategy) NormalizeFormat(format string) string {
	return normalizeFormat(format, "openai")
}

// SegmentText splits text into sentence-level segments capped at OpenAI's
// 4,096-character input limit.
func (openAIStrategy) SegmentText(text string) []string {
	return splitIntoSentences(text)
}

// InitialWorkUnits queues ALL incomplete segments in parallel.
// OpenAI TTS has no request stitching, so segments are independent.
func (openAIStrategy) InitialWorkUnits(j *Job) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for _, ch := range j.State.Chapters {
		// Check if all segments are already complete
		if j.State.IsChapterComplete(ch.DocID) {
			// Chapter is complete - check if concatenation is needed
			progress := j.State.ChapterProgress[ch.DocID]
			if progress == nil || progress.AudioFile == "" {
				// Segments are complete but concatenation not done - queue concatenation
				concatUnit := j.createConcatenateWorkUnit(ch.DocID, ch.ChapterIdx)
				units = append(units, concatUnit)
			}
			continue // No TTS segments needed for this chapter
		}

		// Queue all incomplete segments for this chapter.
		for paragraphIdx, paragraph := range ch.Paragraphs {
			if j.State.IsSegmentComplete(ch.DocID, paragraphIdx) {
				continue
			}

			unit := j.createTTSWorkUnit(ch, paragraphIdx, paragraph, nil)
			units = append(units, unit)
		}
	}

	return units
}

// OnSegmentComplete persists a finished TTS segment and, when the chapter is
// complete, recalculates deterministic offsets (segments can complete out of
// order) before queueing chapter concatenation.
func (openAIStrategy) OnSegmentComplete(ctx context.Context, j *Job, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	info, ok := j.Tracker.Get(result.WorkUnitID)
	if !ok {
		return nil, nil // Not our work unit
	}

	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)

	ttsResult := result.TTSResult
	if ttsResult == nil {
		j.Tracker.Remove(result.WorkUnitID)
		err := fmt.Errorf("TTS result is nil")
		j.markBookAudioFailed(ctx, defraClient, err)
		return nil, err
	}

	// Save audio file to disk (use DocID for stable paths)
	format := j.State.Format
	if format == "" {
		format = "mp3"
	}
	audioPath := j.State.HomeDir.SegmentAudioPath(
		j.State.BookID, info.ChapterDocID, info.ParagraphIdx, format)

	if err := os.WriteFile(audioPath, ttsResult.Audio, 0644); err != nil {
		j.Tracker.Remove(result.WorkUnitID)
		err := fmt.Errorf("failed to write audio file: %w", err)
		j.markBookAudioFailed(ctx, defraClient, err)
		return nil, err
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
		if ch.DocID == info.ChapterDocID {
			if info.ParagraphIdx < len(ch.Paragraphs) {
				paragraph = ch.Paragraphs[info.ParagraphIdx]
			}
			break
		}
	}

	// Save to DefraDB
	docID, err := j.saveAudioSegment(ctx, defraClient, info.ChapterDocID, info.ChapterIdx, info.ParagraphIdx, segResult, paragraph)
	if err != nil {
		j.Tracker.Remove(result.WorkUnitID)
		persistErr := fmt.Errorf("failed to save audio segment: %w", err)
		j.markBookAudioFailed(ctx, defraClient, persistErr)
		return nil, persistErr
	}
	segResult.DocID = docID

	// Update state
	j.State.MarkSegmentComplete(info.ChapterDocID, info.ChapterIdx, info.ParagraphIdx, segResult)

	if logger != nil {
		logger.Debug("TTS segment complete",
			"chapter_doc_id", info.ChapterDocID,
			"chapter_idx", info.ChapterIdx,
			"paragraph", info.ParagraphIdx,
			"duration_ms", ttsResult.DurationMS,
			"cost", ttsResult.CostUSD)
	}

	var newUnits []jobs.WorkUnit

	// Queue concatenation when chapter is complete.
	if j.State.IsChapterComplete(info.ChapterDocID) {
		// Segments can complete out of order. Recalculate deterministic offsets
		// from the final ordered segment durations before chapter concatenation.
		if err := j.recalculateChapterOffsets(ctx, defraClient, info.ChapterDocID); err != nil {
			j.Tracker.Remove(result.WorkUnitID)
			persistErr := fmt.Errorf("failed to recalculate chapter offsets: %w", err)
			j.markBookAudioFailed(ctx, defraClient, persistErr)
			return nil, persistErr
		}

		concatUnit := j.createConcatenateWorkUnit(info.ChapterDocID, info.ChapterIdx)
		newUnits = append(newUnits, concatUnit)
	}

	return newUnits, nil
}

func (j *Job) recalculateChapterOffsets(ctx context.Context, client *defra.Client, chapterDocID string) error {
	progress := j.State.ChapterProgress[chapterDocID]
	if progress == nil {
		return fmt.Errorf("no progress for chapter %s", chapterDocID)
	}

	offset := 0
	for idx := 0; idx < progress.TotalSegments; idx++ {
		seg, ok := progress.Segments[idx]
		if !ok || seg == nil {
			return fmt.Errorf("missing segment %d for chapter %s", idx, chapterDocID)
		}

		if seg.StartOffsetMS != offset {
			seg.StartOffsetMS = offset
			if seg.DocID != "" {
				if err := j.updateAudioSegmentOffset(ctx, client, seg.DocID, offset); err != nil {
					return err
				}
			}
		}
		offset += seg.DurationMS
	}

	return nil
}

func (j *Job) updateAudioSegmentOffset(ctx context.Context, client *defra.Client, segmentDocID string, startOffsetMS int) error {

	if client != nil {
		mutation := fmt.Sprintf(`mutation {
			update_AudioSegment(filter: {_docID: {_eq: "%s"}}, input: {
				start_offset_ms: %d
			}) {
				_docID
			}
		}`, segmentDocID, startOffsetMS)

		_, err := client.Execute(ctx, mutation, nil)
		return err
	}
	return fmt.Errorf("defra client not available")
}
