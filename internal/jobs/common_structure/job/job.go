package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Start initializes the job and returns the initial work units.
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	// Check if already complete
	if j.Book.Structure.IsComplete() {
		if logger != nil {
			logger.Info("common structure job already complete", "book_id", j.Book.BookID)
		}
		j.IsDone = true
		return nil, nil
	}

	// Phase 1: Build skeleton (CPU-only, immediate)
	j.CurrentPhase = PhaseBuild
	if err := j.BuildSkeleton(ctx); err != nil {
		return nil, fmt.Errorf("failed to build skeleton: %w", err)
	}

	if logger != nil {
		logger.Info("common structure job starting",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters),
			"phase", j.CurrentPhase)
	}

	// Transition to Extract phase
	return j.transitionToExtract(ctx)
}

// OnComplete is called when a work unit finishes.
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	info, ok := j.GetWorkUnit(result.WorkUnitID)
	if !ok {
		return nil, nil
	}

	logger := svcctx.LoggerFrom(ctx)

	switch info.UnitType {
	case WorkUnitTypeExtract:
		return j.handleExtractComplete(ctx, result, info, logger)

	case WorkUnitTypeClassify:
		return j.handleClassifyComplete(ctx, result, info, logger)

	case WorkUnitTypePolish:
		return j.handlePolishComplete(ctx, result, info, logger)

	default:
		if logger != nil {
			logger.Warn("unknown work unit type", "type", info.UnitType)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, nil
	}
}

// handleExtractComplete handles completion of a text extraction work unit.
func (j *Job) handleExtractComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo, logger interface{ Info(string, ...any); Warn(string, ...any) }) ([]jobs.WorkUnit, error) {
	// Process extraction for this chapter
	chapter := j.GetChapterByEntryID(info.ChapterID)
	if chapter != nil && !chapter.ExtractDone {
		if err := j.ExtractChapterText(ctx, chapter); err != nil {
			if logger != nil {
				logger.Warn("failed to extract chapter text",
					"chapter", info.ChapterID,
					"error", err)
			}
			j.ExtractsFailed++
		} else {
			j.ChaptersExtracted++
		}
	}

	j.RemoveWorkUnit(result.WorkUnitID)

	// Check if all extracts done
	if j.AllExtractsDone() {
		// Persist extract results
		if err := j.PersistExtractResults(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to persist extract results", "error", err)
			}
		}
		return j.transitionToClassify(ctx)
	}

	return nil, nil
}

// handleClassifyComplete handles completion of matter classification.
func (j *Job) handleClassifyComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo, logger interface{ Info(string, ...any); Warn(string, ...any) }) ([]jobs.WorkUnit, error) {
	j.RemoveWorkUnit(result.WorkUnitID)

	if !result.Success {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("classification failed, retrying",
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			// Create retry work unit
			unit, err := j.CreateClassifyWorkUnit(ctx)
			if err != nil {
				if logger != nil {
					logger.Warn("failed to create retry classify unit", "error", err)
				}
				return j.transitionToPolish(ctx)
			}
			// Update retry count in tracker
			j.Tracker.Register(unit.ID, WorkUnitInfo{
				UnitType:   WorkUnitTypeClassify,
				Phase:      PhaseClassify,
				RetryCount: info.RetryCount + 1,
			})
			return []jobs.WorkUnit{*unit}, nil
		}
		if logger != nil {
			logger.Warn("classification permanently failed, skipping to polish")
		}
		return j.transitionToPolish(ctx)
	}

	// Process classification result
	if err := j.ProcessClassifyResult(ctx, result); err != nil {
		if logger != nil {
			logger.Warn("failed to process classification result", "error", err)
		}
	}

	// Persist classification results
	if err := j.PersistClassifyResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist classification results", "error", err)
		}
	}

	return j.transitionToPolish(ctx)
}

// handlePolishComplete handles completion of a polish work unit.
func (j *Job) handlePolishComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo, logger interface{ Info(string, ...any); Warn(string, ...any) }) ([]jobs.WorkUnit, error) {
	// Process polish result for this chapter
	if err := j.ProcessPolishResult(ctx, result, info); err != nil {
		if logger != nil {
			logger.Warn("failed to process polish result",
				"chapter", info.ChapterID,
				"error", err)
		}
	}

	j.RemoveWorkUnit(result.WorkUnitID)

	// Check if all polish done
	if j.AllPolishDone() {
		// Persist polish results
		if err := j.PersistPolishResults(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to persist polish results", "error", err)
			}
		}
		return j.transitionToFinalize(ctx)
	}

	return nil, nil
}

// transitionToExtract starts the extract phase.
func (j *Job) transitionToExtract(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhaseExtract

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to extract phase",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters))
	}

	return j.CreateExtractWorkUnits(ctx)
}

// transitionToClassify starts the classify phase.
func (j *Job) transitionToClassify(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhaseClassify

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to classify phase",
			"book_id", j.Book.BookID)
	}

	unit, err := j.CreateClassifyWorkUnit(ctx)
	if err != nil {
		// Skip to polish if classify fails
		if logger != nil {
			logger.Warn("failed to create classify work unit, skipping to polish", "error", err)
		}
		return j.transitionToPolish(ctx)
	}

	return []jobs.WorkUnit{*unit}, nil
}

// transitionToPolish starts the polish phase.
func (j *Job) transitionToPolish(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhasePolish

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to polish phase",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters))
	}

	return j.CreatePolishWorkUnits(ctx)
}

// transitionToFinalize completes the job.
func (j *Job) transitionToFinalize(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhaseFinalize

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to finalize phase",
			"book_id", j.Book.BookID)
	}

	// Finalize
	if err := j.FinalizeStructure(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to finalize structure", "error", err)
		}
	}

	// Mark job as done
	j.Book.Structure.Complete()
	j.IsDone = true

	if logger != nil {
		logger.Info("common structure job complete",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters),
			"polished", j.ChaptersPolished,
			"failed", j.PolishFailed)
	}

	return nil, nil
}

// Done returns true when the job has no more work.
func (j *Job) Done() bool {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.IsDone
}

// Status returns the current status of the job.
func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	return map[string]string{
		"book_id":             j.Book.BookID,
		"phase":               j.CurrentPhase,
		"chapters_total":      fmt.Sprintf("%d", len(j.Chapters)),
		"chapters_extracted":  fmt.Sprintf("%d", j.ChaptersExtracted),
		"chapters_polished":   fmt.Sprintf("%d", j.ChaptersPolished),
		"polish_failed":       fmt.Sprintf("%d", j.PolishFailed),
		"structure_complete":  fmt.Sprintf("%v", j.Book.Structure.IsComplete()),
		"done":                fmt.Sprintf("%v", j.IsDone),
	}, nil
}

// Progress returns per-provider work unit progress.
func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Total work is: extract (CPU) + classify (1 LLM) + polish (LLM per chapter)
	total := len(j.Chapters) + 1 + len(j.Chapters) // extract + classify + polish
	completed := 0

	// Extract phase
	if j.CurrentPhase != PhaseExtract && j.CurrentPhase != PhaseBuild {
		completed += len(j.Chapters) // All extracts done
	} else {
		completed += j.ChaptersExtracted
	}

	// Classify phase
	if j.CurrentPhase == PhasePolish || j.CurrentPhase == PhaseFinalize || j.IsDone {
		completed++ // Classify done
	}

	// Polish phase
	if j.CurrentPhase == PhaseFinalize || j.IsDone {
		completed += len(j.Chapters) // All polish done
	} else if j.CurrentPhase == PhasePolish {
		completed += j.ChaptersPolished
	}

	return map[string]jobs.ProviderProgress{
		j.Book.TocProvider: {
			TotalExpected: total,
			Completed:     completed,
		},
	}
}
