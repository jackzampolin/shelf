package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
// Returns nil if the image file doesn't exist (expected case - needs extraction first).
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

// HandleOcrComplete processes OCR completion.
// Updates state, persists to DefraDB, and triggers blend if all OCR done.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	// Use common handler for persistence and state update
	allDone, err := common.PersistOCRResult(ctx, state, j.Book.OcrProviders, info.Provider, result.OCRResult)
	if err != nil {
		return nil, fmt.Errorf("failed to persist OCR result for page %d provider %s: %w", info.PageNum, info.Provider, err)
	}

	// If all OCR done, trigger blend
	var units []jobs.WorkUnit
	if allDone {
		blendUnit := j.CreateBlendWorkUnit(info.PageNum, state)
		if blendUnit != nil {
			units = append(units, *blendUnit)
		}
	}

	return units, nil
}
