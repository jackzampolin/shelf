package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateBlendWorkUnit creates a blend LLM work unit.
// Returns nil if blend was handled directly (single provider after filtering).
func (j *Job) CreateBlendWorkUnit(ctx context.Context, pageNum int, state *common.PageState) *jobs.WorkUnit {
	unit, unitID := common.CreateBlendWorkUnit(ctx, j, pageNum, state)

	// Handle single-provider case: no LLM blend needed, save directly
	if unit == nil && strings.HasPrefix(unitID, "single:") {
		text := strings.TrimPrefix(unitID, "single:")
		if err := common.SaveBlendDirect(ctx, state, text); err != nil {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Error("failed to save direct blend", "page_num", pageNum, "error", err)
			}
		}
		return nil
	}

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

	// Check if any book operations should start now
	// - Metadata starts after BlendThresholdForMetadata pages blended (20)
	// - ToC finder starts after ConsecutiveFrontMatterRequired pages blended (30)
	// - Pattern analysis starts after ALL pages blended
	return j.MaybeStartBookOperations(ctx), nil
}
