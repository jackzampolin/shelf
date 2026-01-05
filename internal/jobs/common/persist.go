package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PersistBookStatus persists book status to DefraDB.
func PersistBookStatus(ctx context.Context, bookID string, status string) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document: map[string]any{
			"status": status,
		},
		Op: defra.OpUpdate,
	})
	return nil
}

// PersistMetadataState persists metadata operation state to DefraDB.
func PersistMetadataState(ctx context.Context, bookID string, op *OperationState) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document: map[string]any{
			"metadata_started":  op.IsStarted(),
			"metadata_complete": op.IsComplete(),
			"metadata_failed":   op.IsFailed(),
			"metadata_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
	return nil
}

// PersistTocFinderState persists ToC finder operation state to DefraDB.
func PersistTocFinderState(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finder_started":  op.IsStarted(),
			"finder_complete": op.IsComplete(),
			"finder_failed":   op.IsFailed(),
			"finder_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
	return nil
}

// PersistTocExtractState persists ToC extract operation state to DefraDB.
func PersistTocExtractState(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"extract_started":  op.IsStarted(),
			"extract_complete": op.IsComplete(),
			"extract_failed":   op.IsFailed(),
			"extract_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
	return nil
}
