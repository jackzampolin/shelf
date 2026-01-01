package job

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/ocr"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
// Uses the shared ocr.CreateOcrWorkUnitFunc.
func (j *Job) CreateOcrWorkUnit(ctx context.Context, pageNum int, provider string) *jobs.WorkUnit {
	unit, err := ocr.CreateOcrWorkUnitFunc(
		ocr.OcrWorkUnitParams{
			HomeDir:  j.HomeDir,
			BookID:   j.BookID,
			JobID:    j.RecordID,
			PageNum:  pageNum,
			Provider: provider,
			Stage:    j.Type(),
		},
		func(unitID string) {
			j.RegisterWorkUnit(unitID, WorkUnitInfo{
				PageNum:  pageNum,
				UnitType: "ocr",
				Provider: provider,
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

// HandleOcrComplete processes OCR completion.
// Uses the shared ocr.HandleOcrResultFunc and triggers blend if all OCR done.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.PageState[info.PageNum]

	allDone, err := ocr.HandleOcrResultFunc(ctx, ocr.HandleOcrResultParams{
		PageNum:   info.PageNum,
		Provider:  info.Provider,
		PageDocID: state.PageDocID,
		Result:    result.OCRResult,
	}, state.PageState, j.OcrProviders)

	if err != nil {
		return nil, err
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
