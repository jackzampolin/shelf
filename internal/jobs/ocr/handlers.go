package ocr

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// HandleOcrComplete processes OCR completion for a work unit.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) error {
	state := j.PageState[info.PageNum]

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
		j.TotalCompleted++
	}

	_ = allDone // OCR job doesn't need to trigger next stage
	return nil
}

// CreateRetryUnit creates a retry work unit for a failed operation.
func (j *Job) CreateRetryUnit(info WorkUnitInfo) *jobs.WorkUnit {
	state := j.PageState[info.PageNum]
	if state == nil {
		return nil
	}

	var unit *jobs.WorkUnit

	switch info.UnitType {
	case "extract":
		unit = j.CreateExtractWorkUnit(info.PageNum)
		if unit != nil {
			j.PendingUnits[unit.ID] = WorkUnitInfo{
				PageNum:    info.PageNum,
				UnitType:   "extract",
				RetryCount: info.RetryCount + 1,
			}
		}
	case "ocr":
		unit = j.CreateOcrWorkUnit(info.PageNum, info.Provider)
		if unit != nil {
			j.PendingUnits[unit.ID] = WorkUnitInfo{
				PageNum:    info.PageNum,
				Provider:   info.Provider,
				UnitType:   "ocr",
				RetryCount: info.RetryCount + 1,
			}
		}
	}

	return unit
}
