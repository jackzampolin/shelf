package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
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

	// Recovery: Check persisted phase to resume from correct point
	persistedPhase := j.Book.GetStructurePhase()
	if persistedPhase != "" && persistedPhase != PhaseBuild {
		return j.resumeFromPhase(ctx, persistedPhase, logger)
	}

	// Fresh start: Phase 1: Build skeleton (synchronous)
	j.CurrentPhase = PhaseBuild
	j.Book.SetStructurePhase(PhaseBuild)
	j.persistPhase(ctx)
	if err := j.BuildSkeleton(ctx); err != nil {
		return nil, fmt.Errorf("failed to build skeleton: %w", err)
	}

	// Update chapter count in BookState
	j.Book.SetStructureProgress(len(j.Chapters), 0, 0, 0)
	j.persistPhase(ctx)

	if logger != nil {
		logger.Info("common structure job starting",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters),
			"phase", j.CurrentPhase)
	}

	// Phase 2: Extract text (synchronous - lightweight text processing)
	j.CurrentPhase = PhaseExtract
	j.Book.SetStructurePhase(PhaseExtract)
	j.persistPhase(ctx)
	if err := j.ExtractAllChapters(ctx); err != nil {
		return nil, fmt.Errorf("failed to extract chapters: %w", err)
	}

	// Update extracted count in BookState
	j.Book.SetStructureProgress(len(j.Chapters), j.ChaptersExtracted, 0, 0)

	// Persist extract results
	if err := j.PersistExtractResults(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to persist extract results", "error", err)
		}
	}
	j.persistPhase(ctx)

	// Transition to Classify phase (LLM work units start here)
	return j.transitionToClassify(ctx)
}

// resumeFromPhase handles restart recovery by resuming from the persisted phase.
func (j *Job) resumeFromPhase(ctx context.Context, phase string, logger interface {
	Info(string, ...any)
	Warn(string, ...any)
}) ([]jobs.WorkUnit, error) {
	if logger != nil {
		logger.Info("resuming structure job from persisted phase",
			"book_id", j.Book.BookID,
			"phase", phase)
	}

	// Load existing chapters from DB
	if err := j.loadExistingChapters(ctx); err != nil {
		return nil, fmt.Errorf("failed to load existing chapters: %w", err)
	}

	if logger != nil {
		logger.Info("loaded existing chapters for recovery",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters))
	}

	j.CurrentPhase = phase

	switch phase {
	case PhaseExtract:
		// Re-run extract and continue
		if err := j.ExtractAllChapters(ctx); err != nil {
			return nil, fmt.Errorf("failed to extract chapters: %w", err)
		}
		j.Book.SetStructureProgress(len(j.Chapters), j.ChaptersExtracted, 0, 0)
		if err := j.PersistExtractResults(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to persist extract results", "error", err)
			}
		}
		j.persistPhase(ctx)
		return j.transitionToClassify(ctx)

	case PhaseClassify:
		// Skip directly to polish - classify result may have been lost but we can proceed
		if logger != nil {
			logger.Info("classify phase interrupted, skipping to polish",
				"book_id", j.Book.BookID)
		}
		return j.transitionToPolish(ctx)

	case PhasePolish:
		// Resume polish - create work units for unfinished chapters
		return j.CreatePolishWorkUnits(ctx)

	case PhaseFinalize:
		// Re-run finalize
		return j.transitionToFinalize(ctx)

	default:
		// Unknown phase, start fresh from classify
		if logger != nil {
			logger.Warn("unknown persisted phase, starting from classify",
				"phase", phase)
		}
		return j.transitionToClassify(ctx)
	}
}

// OnComplete is called when a work unit finishes.
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	info, ok := j.GetWorkUnit(result.WorkUnitID)
	if !ok {
		// Log unexpected work unit - this shouldn't happen in normal operation
		if logger != nil {
			logger.Warn("received result for unknown work unit",
				"work_unit_id", result.WorkUnitID,
				"job_id", j.ID())
		}
		return nil, nil
	}

	switch info.UnitType {
	case WorkUnitTypeClassify:
		return j.handleClassifyComplete(ctx, result, info, logger)

	case WorkUnitTypePolish:
		return j.handlePolishComplete(ctx, result, info, logger)

	default:
		if logger != nil {
			logger.Warn("unknown work unit type",
				"type", info.UnitType,
				"work_unit_id", result.WorkUnitID)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, nil
	}
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

// transitionToClassify starts the classify phase.
func (j *Job) transitionToClassify(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhaseClassify
	j.Book.SetStructurePhase(PhaseClassify)
	j.persistPhase(ctx)

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to classify phase",
			"book_id", j.Book.BookID)
	}

	unit, err := j.CreateClassifyWorkUnit(ctx)
	if err != nil {
		// Skip to polish if classify fails to create
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
	j.Book.SetStructurePhase(PhasePolish)
	j.persistPhase(ctx)

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
	j.Book.SetStructurePhase(PhaseFinalize)
	j.persistPhase(ctx)

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to finalize phase",
			"book_id", j.Book.BookID)
	}

	// Finalize - this is critical, failure should be reported
	if err := j.FinalizeStructure(ctx); err != nil {
		if logger != nil {
			logger.Error("failed to finalize structure", "error", err)
		}
		return nil, fmt.Errorf("finalization failed: %w", err)
	}

	// Mark job as done only on success
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

// persistPhase persists the current structure phase to DefraDB.
func (j *Job) persistPhase(ctx context.Context) {
	if err := common.PersistStructurePhase(ctx, j.Book); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist structure phase", "error", err)
		}
	}
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

	// Total work: classify (1 LLM) + polish (LLM per chapter)
	// Extract is now synchronous and doesn't contribute to work unit count
	total := 1 + len(j.Chapters) // classify + polish
	completed := 0

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
