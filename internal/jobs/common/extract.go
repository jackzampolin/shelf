package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PersistExtractState saves extraction completion to DefraDB.
// Returns error if pageDocID is empty or sink is not in context.
func PersistExtractState(ctx context.Context, pageDocID string) error {
	if pageDocID == "" {
		return fmt.Errorf("cannot persist extract state: empty page document ID")
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context, extract state will not be persisted for page %s", pageDocID)
	}

	// Fire-and-forget write - sink batches and logs errors internally
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      pageDocID,
		Document:   map[string]any{"extract_complete": true},
		Op:         defra.OpUpdate,
	})

	return nil
}
