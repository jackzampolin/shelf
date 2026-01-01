package ocr

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// handleOcrComplete processes OCR completion for a work unit.
func (j *Job) handleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) error {
	state := j.pageState[info.PageNum]

	allDone, err := HandleOcrResultFunc(ctx, HandleOcrResultParams{
		PageNum:   info.PageNum,
		Provider:  info.Provider,
		PageDocID: state.PageDocID,
		Result:    result.OCRResult,
	}, state, j.OcrProviders)

	if err != nil {
		return err
	}

	// Update job-level completed count
	if result.OCRResult != nil {
		j.totalCompleted++
	}

	_ = allDone // OCR job doesn't need to trigger next stage
	return nil
}

// createRetryUnit creates a retry work unit for a failed operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo) *jobs.WorkUnit {
	state := j.pageState[info.PageNum]
	if state == nil {
		return nil
	}

	var unit *jobs.WorkUnit

	switch info.UnitType {
	case WorkUnitTypeExtract:
		unit = j.createExtractWorkUnit(info.PageNum)
		if unit != nil {
			j.pendingUnits[unit.ID] = WorkUnitInfo{
				PageNum:    info.PageNum,
				UnitType:   WorkUnitTypeExtract,
				RetryCount: info.RetryCount + 1,
			}
		}
	case WorkUnitTypeOCR:
		unit = j.createOcrWorkUnit(ctx, info.PageNum, info.Provider)
		if unit != nil {
			j.pendingUnits[unit.ID] = WorkUnitInfo{
				PageNum:    info.PageNum,
				Provider:   info.Provider,
				UnitType:   WorkUnitTypeOCR,
				RetryCount: info.RetryCount + 1,
			}
		}
	}

	return unit
}
