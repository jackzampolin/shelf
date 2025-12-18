package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/pipeline/prompts/label"
)

// CreateLabelWorkUnit creates a label extraction LLM work unit.
func (j *Job) CreateLabelWorkUnit(pageNum int, state *PageState) *jobs.WorkUnit {
	query := fmt.Sprintf(`{
		Page(filter: {_docID: {_eq: "%s"}}) {
			blend_markdown
		}
	}`, state.PageDocID)

	resp, err := j.DefraClient.Query(context.Background(), query)
	if err != nil {
		return nil
	}

	var blendedText string
	if pages, ok := resp.Data["Page"].([]any); ok && len(pages) > 0 {
		if page, ok := pages[0].(map[string]any); ok {
			if bm, ok := page["blend_markdown"].(string); ok {
				blendedText = bm
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
		BlendedText: blendedText,
	})
	unit.ID = unitID
	unit.Provider = j.LabelProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = fmt.Sprintf("page_%04d_label", pageNum)
	unit.Metrics = metrics

	return unit
}

// HandleLabelComplete processes label completion.
func (j *Job) HandleLabelComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.PageState[info.PageNum]
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	if result.ChatResult != nil && result.ChatResult.ParsedJSON != nil {
		if err := j.SaveLabelResult(ctx, state, result.ChatResult.ParsedJSON); err != nil {
			return nil, fmt.Errorf("failed to save label result: %w", err)
		}
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

	update := map[string]any{
		"label_complete": true,
	}

	if labelResult.PageNumber != nil {
		update["page_number_label"] = *labelResult.PageNumber
	}
	if labelResult.RunningHeader != nil {
		update["running_header"] = *labelResult.RunningHeader
	}

	return j.DefraClient.Update(ctx, "Page", state.PageDocID, update)
}
