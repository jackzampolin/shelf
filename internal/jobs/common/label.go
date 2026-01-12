package common

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
// Returns nil if no blended text is available.
// The caller is responsible for registering the work unit with their tracker.
func CreateLabelWorkUnit(ctx context.Context, jc JobContext, pageNum int, state *PageState) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	logger := svcctx.LoggerFrom(ctx)

	// Get blended text from BookState (written through from blend stage)
	blendedText := state.GetBlendedText()
	if blendedText == "" {
		if logger != nil {
			logger.Debug("cannot create label work unit: no blended text in state",
				"page_num", pageNum)
		}
		return nil, ""
	}

	unitID := uuid.New().String()

	unit := label.CreateWorkUnit(label.Input{
		BlendedText:          blendedText,
		SystemPromptOverride: book.GetPrompt(label.SystemPromptKey),
		UserPromptOverride:   book.GetPrompt(label.UserPromptKey),
	})
	unit.ID = unitID
	unit.Provider = book.LabelProvider
	unit.JobID = jc.ID()
	unit.Priority = jobs.PriorityForStage("label")

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     "label",
		ItemKey:   fmt.Sprintf("page_%04d_label", pageNum),
		PromptKey: label.SystemPromptKey,
		PromptCID: book.GetPromptCID(label.SystemPromptKey),
	}

	return unit, unitID
}

// SaveLabelResult parses the label result, persists to DefraDB, and updates page state (thread-safe).
func SaveLabelResult(ctx context.Context, state *PageState, parsedJSON any) error {
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

	// Fire-and-forget write - sink batches and logs errors internally
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.GetPageDocID(),
		Document:   update,
		Op:         defra.OpUpdate,
	})

	// Write-through: Update in-memory cache with all persisted data (thread-safe)
	state.SetLabelResultCached(labelResult.PageNumber, labelResult.RunningHeader)

	return nil
}
