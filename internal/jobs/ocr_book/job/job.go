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

	// Set book status to processing
	if err := common.PersistBookStatus(ctx, j.Book.BookID, string(BookStatusProcessing)); err != nil {
		if logger != nil {
			logger.Warn("failed to persist book status", "error", err)
		}
	}

	// Create any missing page records in DB
	createdCount, err := common.CreateMissingPages(ctx, j.Book)
	if err != nil {
		return nil, fmt.Errorf("failed to create page records: %w", err)
	}
	if createdCount > 0 && logger != nil {
		logger.Info("created page records", "count", createdCount)
	}

	// Generate work units for all pages
	var units []jobs.WorkUnit
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

		if !state.IsExtractDone() {
			if unit := j.CreateExtractWorkUnit(pageNum); unit != nil {
				units = append(units, *unit)
			}
		} else {
			newUnits := j.GeneratePageWorkUnits(ctx, pageNum, state)
			units = append(units, newUnits...)
		}
	}

	if logger != nil {
		logger.Info("ocr job started",
			"book_id", j.Book.BookID,
			"total_pages", j.Book.TotalPages,
			"work_units", len(units))
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
			logger.Error("page operation failed after retries",
				"unit_type", info.UnitType,
				"page_num", info.PageNum,
				"retry_count", info.RetryCount,
				"error", result.Error)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, fmt.Errorf("work unit failed (%s): %v", info.UnitType, result.Error)
	}

	var newUnits []jobs.WorkUnit
	var handlerErr error

	switch info.UnitType {
	case WorkUnitTypeExtract:
		units, err := j.HandleExtractComplete(ctx, info, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case WorkUnitTypeOCR:
		units, err := j.HandleOcrComplete(ctx, info, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case WorkUnitTypeBlend:
		if err := j.HandleBlendComplete(ctx, info, result); err != nil {
			handlerErr = err
		}
	}

	if handlerErr != nil {
		if info.RetryCount < MaxPageOpRetries {
			if logger != nil {
				logger.Warn("handler failed, retrying",
					"unit_type", info.UnitType,
					"page_num", info.PageNum,
					"retry_count", info.RetryCount,
					"error", handlerErr)
			}
			retryUnit := j.createRetryUnit(ctx, info, logger)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, handlerErr
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	j.CheckCompletion(ctx)

	return newUnits, nil
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	extractDone, ocrDone, blendDone := 0, 0, 0
	j.Book.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsExtractDone() {
			extractDone++
		}
		allOcr := true
		for _, provider := range j.Book.OcrProviders {
			if !state.OcrComplete(provider) {
				allOcr = false
				break
			}
		}
		if allOcr {
			ocrDone++
		}
		if state.IsBlendDone() {
			blendDone++
		}
	})

	return map[string]string{
		"book_id":          j.Book.BookID,
		"total_pages":      fmt.Sprintf("%d", j.Book.TotalPages),
		"extract_complete": fmt.Sprintf("%d", extractDone),
		"ocr_complete":     fmt.Sprintf("%d", ocrDone),
		"blend_complete":   fmt.Sprintf("%d", blendDone),
		"done":             fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.BaseJob.ProviderProgress()
}

// GeneratePageWorkUnits creates work units for a page based on its current state.
func (j *Job) GeneratePageWorkUnits(ctx context.Context, pageNum int, state *PageState) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	// Check if OCR is needed for any provider
	allOcrDone := true
	for _, provider := range j.Book.OcrProviders {
		if !state.OcrComplete(provider) {
			allOcrDone = false
			unit := j.CreateOcrWorkUnit(ctx, pageNum, provider)
			if unit != nil {
				units = append(units, *unit)
			}
		}
	}

	// If all OCR done but blend not done, create blend unit
	if allOcrDone && !state.IsBlendDone() {
		unit := j.CreateBlendWorkUnit(pageNum, state)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// CheckCompletion checks if the entire job is complete.
func (j *Job) CheckCompletion(ctx context.Context) {
	if !j.AllPagesBlendComplete() {
		return
	}

	j.IsDone = true

	if err := common.PersistBookStatus(ctx, j.Book.BookID, string(BookStatusComplete)); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist book status", "error", err)
		}
	}
}

// CreateExtractWorkUnit creates a CPU work unit to extract a page from PDF.
func (j *Job) CreateExtractWorkUnit(pageNum int) *jobs.WorkUnit {
	unit, unitID := common.CreateExtractWorkUnit(j, pageNum)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			PageNum:  pageNum,
			UnitType: WorkUnitTypeExtract,
		})
	}
	return unit
}

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
func (j *Job) CreateOcrWorkUnit(ctx context.Context, pageNum int, provider string) *jobs.WorkUnit {
	unit, unitID := common.CreateOcrWorkUnit(ctx, j, pageNum, provider)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			PageNum:  pageNum,
			UnitType: WorkUnitTypeOCR,
			Provider: provider,
		})
	}
	return unit
}

// CreateBlendWorkUnit creates a blend LLM work unit.
func (j *Job) CreateBlendWorkUnit(pageNum int, state *PageState) *jobs.WorkUnit {
	unit, unitID := common.CreateBlendWorkUnit(j, pageNum, state)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			PageNum:  pageNum,
			UnitType: WorkUnitTypeBlend,
		})
	}
	return unit
}

// HandleExtractComplete processes extract completion.
func (j *Job) HandleExtractComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetOrCreatePage(info.PageNum)
	state.SetExtractDone(true)

	if err := common.PersistExtractState(ctx, state.GetPageDocID()); err != nil {
		return nil, fmt.Errorf("failed to persist extract state for page %d: %w", info.PageNum, err)
	}

	return j.GeneratePageWorkUnits(ctx, info.PageNum, state), nil
}

// HandleOcrComplete processes OCR completion.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	allDone, err := common.PersistOCRResult(ctx, state, j.Book.OcrProviders, info.Provider, result.OCRResult)
	if err != nil {
		return nil, fmt.Errorf("failed to persist OCR result for page %d provider %s: %w", info.PageNum, info.Provider, err)
	}

	var units []jobs.WorkUnit
	if allDone {
		blendUnit := j.CreateBlendWorkUnit(info.PageNum, state)
		if blendUnit != nil {
			units = append(units, *blendUnit)
		}
	}

	return units, nil
}

// HandleBlendComplete processes blend completion.
func (j *Job) HandleBlendComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) error {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return fmt.Errorf("no state for page %d", info.PageNum)
	}

	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return fmt.Errorf("blend result missing for page %d", info.PageNum)
	}

	if len(j.Book.OcrProviders) == 0 {
		return fmt.Errorf("no OCR providers configured for page %d", info.PageNum)
	}
	primaryProvider := j.Book.OcrProviders[0]
	_, err := common.SaveBlendResult(ctx, state, primaryProvider, result.ChatResult.ParsedJSON)
	if err != nil {
		return fmt.Errorf("failed to save blend result: %w", err)
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
			"unit_type", info.UnitType,
			"page_num", info.PageNum,
			"retry_count", newRetryCount)
	}

	var unit *jobs.WorkUnit
	switch info.UnitType {
	case WorkUnitTypeExtract:
		unit = j.CreateExtractWorkUnit(info.PageNum)
	case WorkUnitTypeOCR:
		unit = j.CreateOcrWorkUnit(ctx, info.PageNum, info.Provider)
	case WorkUnitTypeBlend:
		unit = j.CreateBlendWorkUnit(info.PageNum, state)
	}

	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			PageNum:    info.PageNum,
			UnitType:   info.UnitType,
			Provider:   info.Provider,
			RetryCount: newRetryCount,
		})
	}

	return unit
}
