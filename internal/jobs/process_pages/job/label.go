package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateLabelWorkUnit creates a label extraction LLM work unit.
// Uses state.BlendedText if available, otherwise queries DefraDB.
func (j *Job) CreateLabelWorkUnit(ctx context.Context, pageNum int, state *PageState) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// First try to use cached blended text from state (thread-safe accessor)
	blendedText := state.GetBlendedText()

	// If not cached, query DefraDB
	if blendedText == "" {
		defraClient := svcctx.DefraClientFrom(ctx)
		if defraClient == nil {
			if logger != nil {
				logger.Warn("cannot create label work unit: defra client not in context",
					"page_num", pageNum,
					"page_doc_id", state.GetPageDocID())
			}
			return nil
		}

		query := fmt.Sprintf(`{
			Page(filter: {_docID: {_eq: "%s"}}) {
				blend_markdown
			}
		}`, state.GetPageDocID())

		resp, err := defraClient.Query(ctx, query)
		if err != nil {
			if logger != nil {
				logger.Warn("failed to query blend text for label work unit",
					"page_num", pageNum,
					"error", err)
			}
			return nil
		}

		if pages, ok := resp.Data["Page"].([]any); ok && len(pages) > 0 {
			if page, ok := pages[0].(map[string]any); ok {
				if bm, ok := page["blend_markdown"].(string); ok {
					blendedText = bm
				}
			}
		}
	}

	if blendedText == "" {
		if logger != nil {
			logger.Debug("cannot create label work unit: no blended text available",
				"page_num", pageNum)
		}
		return nil
	}

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		PageNum:  pageNum,
		UnitType: "label",
	})

	unit := label.CreateWorkUnit(label.Input{
		BlendedText:          blendedText,
		SystemPromptOverride: j.GetPrompt(label.SystemPromptKey),
	})
	unit.ID = unitID
	unit.Provider = j.Book.LabelProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = fmt.Sprintf("page_%04d_label", pageNum)
	metrics.PromptKey = label.SystemPromptKey
	metrics.PromptCID = j.GetPromptCID(label.SystemPromptKey)
	unit.Metrics = metrics

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
