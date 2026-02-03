package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
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

	// Mark extraction done (thread-safe)
	state.SetExtractDone(true)

	// Persist to DefraDB using common function (thread-safe accessor)
	cid, err := common.PersistExtractState(ctx, j.Book, state.GetPageDocID())
	if err != nil {
		return nil, fmt.Errorf("failed to persist extract state for page %d: %w", pageNum, err)
	}
	if cid != "" {
		state.SetPageCID(cid)
	}

	// Generate OCR work units now that image is on disk
	return j.GeneratePageWorkUnits(ctx, pageNum, state), nil
}
