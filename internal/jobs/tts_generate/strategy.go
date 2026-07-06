package tts_generate

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

const (
	// requestIDMaxAge is the maximum age for ElevenLabs request IDs used for stitching.
	// ElevenLabs request IDs expire after 2 hours; we use a shorter window for safety.
	requestIDMaxAge = 110 * time.Minute
)

// providerStrategy captures every per-provider orchestration difference.
type providerStrategy interface {
	Provider() string       // pinned provider client name: "elevenlabs" | "openai"
	JobType() string        // the persisted job-type string
	ConcatTaskName() string // "concatenate_chapter" | "concatenate_chapter_openai"
	DefaultFormat() string
	NormalizeFormat(format string) string
	SegmentText(text string) []string
	// InitialWorkUnits: ElevenLabs returns the first incomplete segment per
	// chapter (sequential stitching); OpenAI returns all incomplete segments.
	InitialWorkUnits(j *Job) []jobs.WorkUnit
	// OnSegmentComplete persists the finished segment and returns follow-up
	// units (ElevenLabs: next segment with request-ID threading; OpenAI:
	// offset recalculation then concat when the chapter completes).
	OnSegmentComplete(ctx context.Context, j *Job, res jobs.WorkResult) ([]jobs.WorkUnit, error)
}

// strategyForJobType returns the provider strategy pinned to the persisted
// job-type string. It errors on unknown job types.
func strategyForJobType(jobType string) (providerStrategy, error) {
	switch jobType {
	case JobTypeElevenLabs:
		return elevenLabsStrategy{}, nil
	case JobTypeOpenAI:
		return openAIStrategy{}, nil
	default:
		return nil, fmt.Errorf("unknown TTS job type %q", jobType)
	}
}

// resolvePairing resolves the provider strategy for a persisted job-type
// string and validates the configured provider against it. Provider and
// strategy are always paired: an empty cfgProvider resolves to the strategy's
// pinned provider (config defaults never select the strategy), and a
// conflicting cfgProvider is rejected rather than silently running the wrong
// orchestration.
func resolvePairing(jobType, cfgProvider string) (providerStrategy, string, error) {
	strat, err := strategyForJobType(jobType)
	if err != nil {
		return nil, "", err
	}
	if cfgProvider == "" {
		return strat, strat.Provider(), nil
	}
	if cfgProvider != strat.Provider() {
		return nil, "", fmt.Errorf(
			"TTS provider %q is not valid for job type %q (pinned provider: %q)",
			cfgProvider, jobType, strat.Provider())
	}
	return strat, cfgProvider, nil
}

// elevenLabsStrategy implements the sequential-per-chapter orchestration with
// ElevenLabs request stitching for prosody continuity.
type elevenLabsStrategy struct{}

func (elevenLabsStrategy) Provider() string       { return "elevenlabs" }
func (elevenLabsStrategy) JobType() string        { return JobTypeElevenLabs }
func (elevenLabsStrategy) ConcatTaskName() string { return TaskConcatenateChapter }
func (elevenLabsStrategy) DefaultFormat() string  { return defaultOutputFormat }

func (elevenLabsStrategy) NormalizeFormat(format string) string {
	return normalizeFormat(format, "elevenlabs")
}

func (elevenLabsStrategy) SegmentText(text string) []string {
	return splitIntoParagraphs(text)
}

// InitialWorkUnits queues only the FIRST incomplete segment of each chapter.
// This enables request stitching for prosody continuity within chapters
// while still processing chapters in parallel. Subsequent segments are queued
// in OnSegmentComplete with previous_request_ids.
func (elevenLabsStrategy) InitialWorkUnits(j *Job) []jobs.WorkUnit {
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

	return units
}

// OnSegmentComplete persists a finished TTS segment, threads the ElevenLabs
// request ID for stitching, and queues the next segment in the chapter (or
// chapter concatenation when the chapter is complete).
func (elevenLabsStrategy) OnSegmentComplete(ctx context.Context, j *Job, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
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
		format = "mp3_44100_128"
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
		progress.RequestIDSequence = append(progress.RequestIDSequence, RequestIDRef{
			ID:        ttsResult.RequestID,
			CreatedAt: time.Now().UTC(),
		})
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
			"cost", ttsResult.CostUSD,
			"request_id", ttsResult.RequestID)
	}

	var newUnits []jobs.WorkUnit

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

	return newUnits, nil
}

// getPreviousRequestIDs returns up to 3 most recent request IDs for a chapter.
// Used for ElevenLabs request stitching to maintain prosody continuity.
func (j *Job) getPreviousRequestIDs(chapterDocID string) []string {
	progress := j.State.ChapterProgress[chapterDocID]
	if progress == nil || len(progress.RequestIDSequence) == 0 {
		return nil
	}

	// Drop stale request IDs before building the request.
	// ElevenLabs request IDs expire after ~2 hours.
	cutoff := time.Now().Add(-requestIDMaxAge)
	fresh := progress.RequestIDSequence[:0]
	for _, ref := range progress.RequestIDSequence {
		if ref.ID == "" {
			continue
		}
		if ref.CreatedAt.IsZero() || ref.CreatedAt.After(cutoff) {
			fresh = append(fresh, ref)
		}
	}
	progress.RequestIDSequence = fresh
	if len(progress.RequestIDSequence) == 0 {
		return nil
	}

	// ElevenLabs supports up to 3 previous request IDs
	refs := progress.RequestIDSequence
	if len(refs) > 3 {
		refs = refs[len(refs)-3:]
	}

	// Return a copy to avoid mutation
	result := make([]string, 0, len(refs))
	for _, ref := range refs {
		result = append(result, ref.ID)
	}
	return result
}

func (j *Job) clearRequestIDSequence(chapterDocID string) {
	progress := j.State.ChapterProgress[chapterDocID]
	if progress == nil {
		return
	}
	progress.RequestIDSequence = nil
}

func shouldDisableRequestStitching(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "previous_request_ids") ||
		strings.Contains(msg, "previous request ids") ||
		(strings.Contains(msg, "request id") && strings.Contains(msg, "older than")) ||
		(strings.Contains(msg, "request") && strings.Contains(msg, "two hours"))
}
