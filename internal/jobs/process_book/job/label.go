package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// CreateLabelWorkUnit creates a label extraction LLM work unit.
// Uses state.BlendedText if available, otherwise queries DefraDB.
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
// Must be called with j.Mu held.
func (j *Job) HandleLabelComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	// Require valid result to mark label as done
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return nil, fmt.Errorf("label result missing for page %d", info.PageNum)
	}

	// Use common handler for persistence and state update
	if err := common.SaveLabelResult(ctx, state, result.ChatResult.ParsedJSON); err != nil {
		return nil, fmt.Errorf("failed to save label result: %w", err)
	}

	// Check if we should start book-level operations
	return j.MaybeStartBookOperations(ctx), nil
}
