package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

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

	// Update in-memory state (thread-safe)
	state.SetLabelDone(true)

	return nil
}
