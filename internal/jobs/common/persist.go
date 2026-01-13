package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// SendToSink sends a write operation to the DefraDB sink from context.
// Returns an error if sink is not in context.
// This is a convenience helper that consolidates the common pattern of
// extracting the sink, checking nil, and sending.
func SendToSink(ctx context.Context, op defra.WriteOp) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}
	sink.Send(op)
	return nil
}

// PersistBookStatus persists book status to DefraDB.
func PersistBookStatus(ctx context.Context, bookID string, status string) error {
	return SendToSink(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document: map[string]any{
			"status": status,
		},
		Op: defra.OpUpdate,
	})
}

// PersistMetadataState persists metadata operation state to DefraDB.
func PersistMetadataState(ctx context.Context, bookID string, op *OperationState) error {
	return SendToSink(ctx, defra.WriteOp{
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
}

// PersistTocFinderState persists ToC finder operation state to DefraDB.
func PersistTocFinderState(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}
	return SendToSink(ctx, defra.WriteOp{
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
}

// PersistTocExtractState persists ToC extract operation state to DefraDB.
func PersistTocExtractState(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}
	return SendToSink(ctx, defra.WriteOp{
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
}

// PersistPatternAnalysisState persists pattern analysis operation state to DefraDB.
func PersistPatternAnalysisState(ctx context.Context, bookID string, op *OperationState) error {
	return SendToSink(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document: map[string]any{
			"pattern_analysis_started":  op.IsStarted(),
			"pattern_analysis_complete": op.IsComplete(),
			"pattern_analysis_failed":   op.IsFailed(),
			"pattern_analysis_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
}

// PersistTocLinkState persists ToC link operation state to DefraDB.
func PersistTocLinkState(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}
	return SendToSink(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"link_started":  op.IsStarted(),
			"link_complete": op.IsComplete(),
			"link_failed":   op.IsFailed(),
			"link_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
}

// PersistTocFinalizeState persists ToC finalize operation state to DefraDB.
func PersistTocFinalizeState(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}
	return SendToSink(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_started":  op.IsStarted(),
			"finalize_complete": op.IsComplete(),
			"finalize_failed":   op.IsFailed(),
			"finalize_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
}

// PersistStructureState persists structure operation state to DefraDB.
func PersistStructureState(ctx context.Context, bookID string, op *OperationState) error {
	return SendToSink(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document: map[string]any{
			"structure_started":  op.IsStarted(),
			"structure_complete": op.IsComplete(),
			"structure_failed":   op.IsFailed(),
			"structure_retries":  op.GetRetries(),
		},
		Op: defra.OpUpdate,
	})
}

// PersistStructurePhase persists structure phase tracking data from BookState to DefraDB.
func PersistStructurePhase(ctx context.Context, book *BookState) error {
	total, extracted, polished, failed := book.GetStructureProgress()
	return SendToSink(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"structure_phase":              book.GetStructurePhase(),
			"structure_chapters_total":     total,
			"structure_chapters_extracted": extracted,
			"structure_chapters_polished":  polished,
			"structure_polish_failed":      failed,
		},
		Op: defra.OpUpdate,
	})
}
