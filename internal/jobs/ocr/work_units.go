package ocr

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// createOcrWorkUnit creates an OCR work unit for a page and provider.
// Note: ctx is only used for logging; caller must hold j.mu.
func (j *Job) createOcrWorkUnit(ctx context.Context, pageNum int, provider string) *jobs.WorkUnit {
	unit, err := CreateOcrWorkUnitFunc(
		OcrWorkUnitParams{
			HomeDir:  j.HomeDir,
			BookID:   j.BookID,
			JobID:    j.RecordID,
			PageNum:  pageNum,
			Provider: provider,
			Stage:    JobType,
		},
		func(unitID string) {
			j.registerWorkUnit(unitID, WorkUnitInfo{
				PageNum:  pageNum,
				Provider: provider,
				UnitType: WorkUnitTypeOCR,
			})
		},
	)
	if err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to create OCR work unit",
				"page_num", pageNum,
				"provider", provider,
				"error", err)
		}
		return nil
	}
	return unit
}

// registerWorkUnit registers a pending work unit.
func (j *Job) registerWorkUnit(unitID string, info WorkUnitInfo) {
	j.pendingUnits[unitID] = info
}

// getWorkUnit gets a pending work unit without removing it.
func (j *Job) getWorkUnit(unitID string) (WorkUnitInfo, bool) {
	info, ok := j.pendingUnits[unitID]
	return info, ok
}

// removeWorkUnit removes a pending work unit.
func (j *Job) removeWorkUnit(unitID string) {
	delete(j.pendingUnits, unitID)
}

// generateAllWorkUnits creates work units for all pages.
// If a page needs extraction, creates extract work unit (OCR follows after extraction).
// If a page already has an image, creates OCR work units directly.
func (j *Job) generateAllWorkUnits(ctx context.Context) []jobs.WorkUnit {
	var units []jobs.WorkUnit

	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		state := j.pageState[pageNum]
		if state == nil {
			continue
		}

		// Check if page needs extraction first
		if j.needsExtraction(pageNum) {
			if unit := j.createExtractWorkUnit(pageNum); unit != nil {
				units = append(units, *unit)
			}
			continue // OCR work units will be created after extraction completes
		}

		// Image exists - create OCR work units for providers that haven't completed
		for _, provider := range j.OcrProviders {
			if !state.OcrComplete(provider) {
				if unit := j.createOcrWorkUnit(ctx, pageNum, provider); unit != nil {
					units = append(units, *unit)
				}
			}
		}
	}

	return units
}
