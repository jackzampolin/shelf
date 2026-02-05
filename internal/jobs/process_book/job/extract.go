package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

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

// HandleExtractComplete processes the result of a page extraction.
func (j *Job) HandleExtractComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	pageNum := info.PageNum
	state := j.Book.GetOrCreatePage(pageNum)
	logger := svcctx.LoggerFrom(ctx)

	// Mark extraction done (thread-safe)
	state.SetExtractDone(true)

	// Persist to DefraDB using common function (thread-safe accessor)
	pageDocID := state.GetPageDocID()
	if logger != nil {
		logger.Debug("HandleExtractComplete: persisting extract state",
			"page_num", pageNum,
			"page_doc_id", pageDocID,
			"has_doc_id", pageDocID != "")
	}
	cid, err := common.PersistExtractState(ctx, j.Book, pageDocID)
	if err != nil {
		if logger != nil {
			logger.Error("HandleExtractComplete: persist failed - OCR units will NOT be created",
				"page_num", pageNum,
				"page_doc_id", pageDocID,
				"error", err)
		}
		return nil, fmt.Errorf("failed to persist extract state for page %d: %w", pageNum, err)
	}
	if cid != "" {
		state.SetPageCID(cid)
	}

	// Generate OCR work units now that image is on disk
	units := j.GeneratePageWorkUnits(ctx, pageNum, state)
	if logger != nil {
		logger.Debug("HandleExtractComplete: generated work units",
			"page_num", pageNum,
			"ocr_units_created", len(units))
	}
	return units, nil
}
