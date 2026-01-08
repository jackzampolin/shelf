package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	// Check if already complete
	if j.Book.TocFinalize.IsComplete() {
		if logger != nil {
			logger.Info("finalize toc job already complete", "book_id", j.Book.BookID)
		}
		j.IsDone = true
		return nil, nil
	}

	// Mark finalize as started
	if j.Book.TocFinalize.CanStart() {
		if err := j.Book.TocFinalize.Start(); err != nil {
			return nil, fmt.Errorf("failed to start finalize operation: %w", err)
		}
		j.PersistTocFinalizeState(ctx)
	}

	// Start with pattern analysis phase
	j.CurrentPhase = PhasePattern

	if logger != nil {
		logger.Info("finalize toc job starting",
			"book_id", j.Book.BookID,
			"entries_count", len(j.LinkedEntries),
			"phase", j.CurrentPhase)
	}

	// Create pattern analysis work unit
	unit, err := j.CreatePatternWorkUnit(ctx)
	if err != nil {
		return nil, fmt.Errorf("failed to create pattern work unit: %w", err)
	}

	if unit == nil {
		// No work to do - skip to completion
		j.Book.TocFinalize.Complete()
		j.PersistTocFinalizeState(ctx)
		j.IsDone = true
		return nil, nil
	}

	return []jobs.WorkUnit{*unit}, nil
}

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

	// Handle based on work unit type
	switch info.UnitType {
	case WorkUnitTypePattern:
		return j.handlePatternComplete(ctx, result, info, logger)

	case WorkUnitTypeDiscover:
		return j.handleDiscoverComplete(ctx, result, info, logger)

	case WorkUnitTypeGap:
		return j.handleGapComplete(ctx, result, info, logger)

	default:
		if logger != nil {
			logger.Warn("unknown work unit type", "type", info.UnitType)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, nil
	}
}

func (j *Job) handlePatternComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo, logger interface{ Info(string, ...any); Warn(string, ...any) }) ([]jobs.WorkUnit, error) {
	j.RemoveWorkUnit(result.WorkUnitID)

	if !result.Success {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("pattern analysis failed, retrying",
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			unit, err := j.CreatePatternWorkUnit(ctx)
			if err != nil || unit == nil {
				return j.transitionToDiscover(ctx)
			}
			// Update retry count
			j.Tracker.Register(unit.ID, WorkUnitInfo{
				UnitType:   WorkUnitTypePattern,
				Phase:      PhasePattern,
				RetryCount: info.RetryCount + 1,
			})
			return []jobs.WorkUnit{*unit}, nil
		}
		if logger != nil {
			logger.Info("pattern analysis permanently failed, skipping to discover")
		}
		return j.transitionToDiscover(ctx)
	}

	// Process pattern analysis result
	if err := j.ProcessPatternResult(ctx, result); err != nil {
		if logger != nil {
			logger.Warn("failed to process pattern result", "error", err)
		}
	}

	return j.transitionToDiscover(ctx)
}

func (j *Job) handleDiscoverComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo, logger interface{ Info(string, ...any); Warn(string, ...any) }) ([]jobs.WorkUnit, error) {
	if !result.Success {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("chapter finder failed, retrying",
					"entry_key", info.EntryKey,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryDiscoverUnit(ctx, info)
		}
		j.EntriesComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("chapter finder permanently failed",
				"entry_key", info.EntryKey,
				"error", result.Error)
		}
		return j.checkDiscoverCompletion(ctx)
	}

	// Handle successful completion
	units, err := j.HandleDiscoverResult(ctx, result, info)
	if err != nil {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("chapter finder handler failed, retrying",
					"entry_key", info.EntryKey,
					"retry_count", info.RetryCount,
					"error", err)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryDiscoverUnit(ctx, info)
		}
		j.EntriesComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		return j.checkDiscoverCompletion(ctx)
	}

	if len(units) > 0 {
		return units, nil
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkDiscoverCompletion(ctx)
}

func (j *Job) handleGapComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo, logger interface{ Info(string, ...any); Warn(string, ...any) }) ([]jobs.WorkUnit, error) {
	if !result.Success {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("gap investigator failed, retrying",
					"gap_key", info.GapKey,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryGapUnit(ctx, info)
		}
		j.GapsComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("gap investigator permanently failed",
				"gap_key", info.GapKey,
				"error", result.Error)
		}
		return j.checkValidateCompletion(ctx)
	}

	// Handle successful completion
	units, err := j.HandleGapResult(ctx, result, info)
	if err != nil {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("gap investigator handler failed, retrying",
					"gap_key", info.GapKey,
					"retry_count", info.RetryCount,
					"error", err)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryGapUnit(ctx, info)
		}
		j.GapsComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		return j.checkValidateCompletion(ctx)
	}

	if len(units) > 0 {
		return units, nil
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkValidateCompletion(ctx)
}

func (j *Job) transitionToDiscover(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhaseDiscover

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to discover phase",
			"book_id", j.Book.BookID,
			"entries_to_find", len(j.EntriesToFind))
	}

	if len(j.EntriesToFind) == 0 {
		return j.transitionToValidate(ctx)
	}

	// Create work units for all entries to find
	return j.CreateDiscoverWorkUnits(ctx)
}

func (j *Job) transitionToValidate(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.CurrentPhase = PhaseValidate

	// Find gaps in page coverage
	if err := j.FindGaps(ctx); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Info("failed to find gaps", "error", err)
		}
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("transitioning to validate phase",
			"book_id", j.Book.BookID,
			"gaps", len(j.Gaps))
	}

	if len(j.Gaps) == 0 {
		return j.completeJob(ctx)
	}

	// Create work units for all gaps
	return j.CreateGapWorkUnits(ctx)
}

func (j *Job) checkDiscoverCompletion(ctx context.Context) ([]jobs.WorkUnit, error) {
	if j.EntriesComplete >= len(j.EntriesToFind) {
		return j.transitionToValidate(ctx)
	}
	return nil, nil
}

func (j *Job) checkValidateCompletion(ctx context.Context) ([]jobs.WorkUnit, error) {
	if j.GapsComplete >= len(j.Gaps) {
		return j.completeJob(ctx)
	}
	return nil, nil
}

func (j *Job) completeJob(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Book.TocFinalize.Complete()
	j.PersistTocFinalizeState(ctx)
	j.IsDone = true

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Info("finalize toc job complete",
			"book_id", j.Book.BookID,
			"entries_found", j.EntriesFound,
			"gaps_fixed", j.GapsFixes)
	}

	// Submit common-structure job if ready
	if j.Book.Structure.CanStart() {
		j.SubmitCommonStructureJob(ctx)
	}

	return nil, nil
}

// SubmitCommonStructureJob submits the common-structure job to build unified book structure.
func (j *Job) SubmitCommonStructureJob(ctx context.Context) {
	scheduler := svcctx.SchedulerFrom(ctx)
	if scheduler == nil {
		return
	}

	logger := svcctx.LoggerFrom(ctx)

	// Mark structure as started to prevent duplicate submissions
	if err := j.Book.Structure.Start(); err != nil {
		if logger != nil {
			logger.Warn("failed to start structure operation", "error", err)
		}
		return
	}
	common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)

	if err := scheduler.SubmitByType(ctx, "common-structure", j.Book.BookID); err != nil {
		if logger != nil {
			logger.Error("failed to submit common-structure job",
				"book_id", j.Book.BookID,
				"error", err)
		}
		// Reset state on failure to allow retry
		j.Book.Structure.Reset()
		common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)
	} else if logger != nil {
		logger.Info("submitted common-structure job",
			"book_id", j.Book.BookID)
	}
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	return map[string]string{
		"book_id":           j.Book.BookID,
		"phase":             j.CurrentPhase,
		"entries_to_find":   fmt.Sprintf("%d", len(j.EntriesToFind)),
		"entries_complete":  fmt.Sprintf("%d", j.EntriesComplete),
		"entries_found":     fmt.Sprintf("%d", j.EntriesFound),
		"gaps_total":        fmt.Sprintf("%d", len(j.Gaps)),
		"gaps_complete":     fmt.Sprintf("%d", j.GapsComplete),
		"gaps_fixed":        fmt.Sprintf("%d", j.GapsFixes),
		"finalize_started":  fmt.Sprintf("%v", j.Book.TocFinalize.IsStarted()),
		"finalize_complete": fmt.Sprintf("%v", j.Book.TocFinalize.IsComplete()),
		"done":              fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Progress depends on current phase
	total := 1 // Pattern analysis
	completed := 0

	if j.CurrentPhase != PhasePattern {
		completed = 1 // Pattern done
		total += len(j.EntriesToFind)
	}

	if j.CurrentPhase == PhaseDiscover {
		completed += j.EntriesComplete
	}

	if j.CurrentPhase == PhaseValidate {
		completed += len(j.EntriesToFind) // Discover done
		total += len(j.Gaps)
		completed += j.GapsComplete
	}

	return map[string]jobs.ProviderProgress{
		j.Book.TocProvider: {
			TotalExpected: total,
			Completed:     completed,
		},
	}
}

// PersistTocFinalizeState persists ToC finalize state to DefraDB.
func (j *Job) PersistTocFinalizeState(ctx context.Context) {
	if err := common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist ToC finalize state", "error", err)
		}
	}
}
