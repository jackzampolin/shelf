package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
)

// CreateBlendWorkUnit creates a blend LLM work unit.
func (j *Job) CreateBlendWorkUnit(pageNum int, state *PageState) *jobs.WorkUnit {
	var outputs []blend.OCROutput
	for _, provider := range j.Book.OcrProviders {
		// Use thread-safe accessor for OCR results
		if text, ok := state.GetOcrResult(provider); ok && text != "" {
			outputs = append(outputs, blend.OCROutput{
				ProviderName: provider,
				Text:         text,
			})
		}
	}

	if len(outputs) == 0 {
		return nil
	}

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		PageNum:  pageNum,
		UnitType: "blend",
	})

	unit := blend.CreateWorkUnit(blend.Input{
		OCROutputs:           outputs,
		SystemPromptOverride: j.GetPrompt(blend.PromptKey),
	})
	unit.ID = unitID
	unit.Provider = j.Book.BlendProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = fmt.Sprintf("page_%04d_blend", pageNum)
	metrics.PromptKey = blend.PromptKey
	metrics.PromptCID = j.GetPromptCID(blend.PromptKey)
	unit.Metrics = metrics

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
	if len(j.Book.OcrProviders) == 0 {
		return nil, fmt.Errorf("no OCR providers configured for page %d", info.PageNum)
	}
	primaryProvider := j.Book.OcrProviders[0]
	_, err := common.SaveBlendResult(ctx, state, primaryProvider, result.ChatResult.ParsedJSON)
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
