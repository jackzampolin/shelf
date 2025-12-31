package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateLabelWorkUnit creates a label extraction LLM work unit.
// Must be called with j.Mu held. Uses state.BlendedText if available,
// otherwise queries DefraDB.
func (j *Job) CreateLabelWorkUnit(ctx context.Context, pageNum int, state *PageState) *jobs.WorkUnit {
	// First try to use cached blended text from state
	blendedText := state.BlendedText

	// If not cached, query DefraDB
	if blendedText == "" {
		defraClient := svcctx.DefraClientFrom(ctx)
		if defraClient == nil {
			return nil
		}

		query := fmt.Sprintf(`{
			Page(filter: {_docID: {_eq: "%s"}}) {
				blend_markdown
			}
		}`, state.PageDocID)

		resp, err := defraClient.Query(ctx, query)
		if err != nil {
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
	unit.Provider = j.LabelProvider
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
	state := j.PageState[info.PageNum]
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	// Require valid result to mark label as done
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return nil, fmt.Errorf("label result missing for page %d", info.PageNum)
	}

	if err := j.SaveLabelResult(ctx, state, result.ChatResult.ParsedJSON); err != nil {
		return nil, fmt.Errorf("failed to save label result: %w", err)
	}
	state.LabelDone = true

	// Check if we should start book-level operations
	return j.MaybeStartBookOperations(ctx), nil
}

// SaveLabelResult saves the label result to DefraDB.
func (j *Job) SaveLabelResult(ctx context.Context, state *PageState, parsedJSON any) error {
	labelResult, err := label.ParseResult(parsedJSON)
	if err != nil {
		return err
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{
		"label_complete": true,
	}

	if labelResult.PageNumber != nil {
		update["page_number_label"] = *labelResult.PageNumber
	}
	if labelResult.RunningHeader != nil {
		update["running_header"] = *labelResult.RunningHeader
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.PageDocID,
		Document:   update,
		Op:         defra.OpUpdate,
	})
	return nil
}
