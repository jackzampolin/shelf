package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// CreateBlendWorkUnit creates a blend LLM work unit.
func (j *Job) CreateBlendWorkUnit(ctx context.Context, pageNum int, state *PageState) *jobs.WorkUnit {
	unit, unitID := common.CreateBlendWorkUnit(ctx, j, pageNum, state)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			PageNum:  pageNum,
			UnitType: WorkUnitTypeBlend,
		})
	}
	return unit
}

// HandleBlendComplete processes blend completion.
func (j *Job) HandleBlendComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	// Require valid result to mark blend as done
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return nil, fmt.Errorf("blend result missing for page %d", info.PageNum)
	}

	// Use common handler for persistence and state update
	_, err := common.SaveBlendResult(ctx, state, result.ChatResult.ParsedJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to save blend result: %w", err)
	}

	var units []jobs.WorkUnit
	labelUnit := j.CreateLabelWorkUnit(ctx, info.PageNum, state)
	if labelUnit != nil {
		units = append(units, *labelUnit)
	}

	return units, nil
}
