package common

import (
	"context"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PersistExtractState saves extraction completion to DefraDB.
func PersistExtractState(ctx context.Context, pageDocID string) {
	if pageDocID == "" {
		return
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return
	}

	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      pageDocID,
		Document:   map[string]any{"extract_complete": true},
		Op:         defra.OpUpdate,
	})
}
