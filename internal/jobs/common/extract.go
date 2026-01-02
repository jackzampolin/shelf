package common

import (
	"context"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PersistExtractState saves extraction completion to DefraDB.
// Logs warnings if pageDocID is empty or sink is not in context.
func PersistExtractState(ctx context.Context, pageDocID string) {
	logger := svcctx.LoggerFrom(ctx)

	if pageDocID == "" {
		if logger != nil {
			logger.Warn("cannot persist extract state: empty page document ID")
		}
		return
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		if logger != nil {
			logger.Warn("defra sink not in context, extract state will not be persisted",
				"page_doc_id", pageDocID)
		}
		return
	}

	// Fire-and-forget write - sink batches and logs errors internally
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      pageDocID,
		Document:   map[string]any{"extract_complete": true},
		Op:         defra.OpUpdate,
	})
}
