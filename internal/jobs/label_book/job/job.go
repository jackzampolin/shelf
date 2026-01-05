package job

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ID, SetRecordID, Done are inherited from common.BaseJob

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	// Generate label work units for pages that have blend but not label
	var units []jobs.WorkUnit
	pagesNeedingLabel := 0
	pagesWithBlend := 0

	for pageNum := 1; pageNum <= j.Book.TotalPages; pageNum++ {
		if pageNum%100 == 0 {
			if err := ctx.Err(); err != nil {
				return nil, err
			}
		}

		state := j.Book.GetPage(pageNum)
		if state == nil {
			continue
		}

		if state.IsBlendDone() {
			pagesWithBlend++
			if !state.IsLabelDone() {
				pagesNeedingLabel++
				unit := j.CreateLabelWorkUnit(ctx, pageNum, state)
				if unit != nil {
					units = append(units, *unit)
				}
			}
		}
	}

	if logger != nil {
		logger.Info("label job started",
			"book_id", j.Book.BookID,
			"total_pages", j.Book.TotalPages,
			"pages_with_blend", pagesWithBlend,
			"pages_needing_label", pagesNeedingLabel,
			"work_units", len(units))
	}

	// If no work to do, mark as done
	if len(units) == 0 && pagesWithBlend > 0 {
		j.IsDone = true
	}

	return units, nil
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

	if !result.Success {
		if info.RetryCount < MaxPageOpRetries {
			retryUnit := j.createRetryUnit(ctx, info, logger)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		if logger != nil {
			logger.Error("label operation failed after retries",
				"page_num", info.PageNum,
				"retry_count", info.RetryCount,
				"error", result.Error)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, fmt.Errorf("work unit failed: %v", result.Error)
	}

	// Handle label completion
	if err := j.HandleLabelComplete(ctx, info, result); err != nil {
		if info.RetryCount < MaxPageOpRetries {
			if logger != nil {
				logger.Warn("handler failed, retrying",
					"page_num", info.PageNum,
					"retry_count", info.RetryCount,
					"error", err)
			}
			retryUnit := j.createRetryUnit(ctx, info, logger)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, err
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	j.CheckCompletion(ctx)

	return nil, nil
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	blendDone, labelDone := 0, 0
	j.Book.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsBlendDone() {
			blendDone++
		}
		if state.IsLabelDone() {
			labelDone++
		}
	})

	return map[string]string{
		"book_id":        j.Book.BookID,
		"total_pages":    fmt.Sprintf("%d", j.Book.TotalPages),
		"blend_complete": fmt.Sprintf("%d", blendDone),
		"label_complete": fmt.Sprintf("%d", labelDone),
		"done":           fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.BaseJob.ProviderProgress()
}

// CheckCompletion checks if the entire job is complete.
func (j *Job) CheckCompletion(ctx context.Context) {
	if !j.AllPagesLabelComplete() {
		return
	}
	j.IsDone = true
}

// CreateLabelWorkUnit creates a label LLM work unit.
func (j *Job) CreateLabelWorkUnit(ctx context.Context, pageNum int, state *PageState) *jobs.WorkUnit {
	unit, unitID := common.CreateLabelWorkUnit(ctx, j, pageNum, state)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			PageNum:  pageNum,
			UnitType: WorkUnitTypeLabel,
		})
	}
	return unit
}

// HandleLabelComplete processes label completion.
func (j *Job) HandleLabelComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) error {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return fmt.Errorf("no state for page %d", info.PageNum)
	}

	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return fmt.Errorf("label result missing for page %d", info.PageNum)
	}

	if err := common.SaveLabelResult(ctx, state, result.ChatResult.ParsedJSON); err != nil {
		return fmt.Errorf("failed to save label result: %w", err)
	}

	return nil
}

// createRetryUnit creates a retry work unit for a failed operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo, logger *slog.Logger) *jobs.WorkUnit {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil
	}

	newRetryCount := info.RetryCount + 1
	if logger != nil {
		logger.Info("creating retry unit",
			"page_num", info.PageNum,
			"retry_count", newRetryCount)
	}

	unit := j.CreateLabelWorkUnit(ctx, info.PageNum, state)
	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			PageNum:    info.PageNum,
			UnitType:   WorkUnitTypeLabel,
			RetryCount: newRetryCount,
		})
	}

	return unit
}
