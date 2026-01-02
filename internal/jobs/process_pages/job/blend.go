package job

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateBlendWorkUnit creates a blend LLM work unit.
func (j *Job) CreateBlendWorkUnit(pageNum int, state *PageState) *jobs.WorkUnit {
	var outputs []blend.OCROutput
	for _, provider := range j.Book.OcrProviders {
		if text, ok := state.OcrResults[provider]; ok && text != "" {
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

	blendedText, err := j.SaveBlendResult(ctx, state, result.ChatResult.ParsedJSON)
	if err != nil {
		return nil, fmt.Errorf("failed to save blend result: %w", err)
	}

	// Cache blended text for label work unit to avoid re-query
	state.BlendedText = blendedText
	state.BlendDone = true

	var units []jobs.WorkUnit
	labelUnit := j.CreateLabelWorkUnit(ctx, info.PageNum, state)
	if labelUnit != nil {
		units = append(units, *labelUnit)
	}

	return units, nil
}

// SaveBlendResult saves the blend result to DefraDB and returns the blended text.
func (j *Job) SaveBlendResult(ctx context.Context, state *PageState, parsedJSON any) (string, error) {
	blendResult, err := blend.ParseResult(parsedJSON)
	if err != nil {
		return "", err
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return "", fmt.Errorf("defra sink not in context")
	}

	primaryProvider := j.Book.OcrProviders[0]
	baseText := state.OcrResults[primaryProvider]
	blendedText := blend.ApplyCorrections(baseText, blendResult.Corrections)

	correctionsJSON, _ := json.Marshal(blendResult.Corrections)

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.PageDocID,
		Document: map[string]any{
			"blend_markdown":    blendedText,
			"blend_corrections": string(correctionsJSON),
			"blend_confidence":  blendResult.Confidence,
			"blend_complete":    true,
		},
		Op: defra.OpUpdate,
	})
	return blendedText, nil
}
