package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// SendToSinkSync sends a write operation and waits for confirmation.
// Use this for critical operations where you need to ensure the write succeeded.
func SendToSinkSync(ctx context.Context, op defra.WriteOp) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}
	_, err := sink.SendSync(ctx, op)
	return err
}

// SendTracked sends a write operation and updates CID tracking on BookState.
func SendTracked(ctx context.Context, book *BookState, op defra.WriteOp) (defra.WriteResult, error) {
	var result defra.WriteResult
	var err error

	if book != nil && book.Store != nil {
		result, err = book.Store.SendSync(ctx, op)
	} else {
		sink := svcctx.DefraSinkFrom(ctx)
		if sink == nil {
			return defra.WriteResult{}, fmt.Errorf("defra sink not in context")
		}
		result, err = sink.SendSync(ctx, op)
	}
	if err != nil {
		return result, err
	}
	if book != nil {
		docID := result.DocID
		if docID == "" {
			docID = op.DocID
		}
		book.TrackWrite(op.Collection, docID, result.CID)
	}
	return result, nil
}

// SendManyTracked sends a batch of writes and updates CID tracking on BookState.
func SendManyTracked(ctx context.Context, book *BookState, ops []defra.WriteOp) ([]defra.WriteResult, error) {
	var results []defra.WriteResult
	var err error

	if book != nil && book.Store != nil {
		results, err = book.Store.SendManySync(ctx, ops)
		if err != nil {
			return results, err
		}
	} else {
		sink := svcctx.DefraSinkFrom(ctx)
		if sink == nil {
			return nil, fmt.Errorf("defra sink not in context")
		}
		results, err = sink.SendManySync(ctx, ops)
		if err != nil {
			return results, err
		}
	}
	if book != nil {
		for i, result := range results {
			docID := result.DocID
			if docID == "" && i < len(ops) {
				docID = ops[i].DocID
			}
			book.TrackWrite(ops[i].Collection, docID, result.CID)
		}
	}
	return results, nil
}

// --- Generic Operation State Persistence ---

// PersistOpState persists operation state to DefraDB and updates CID tracking.
// Uses OpConfig to determine collection, field prefix, and document ID.
// If book.Store is set, uses it directly; otherwise falls back to context.
//
// Deprecated: Use PersistOpStateAsync instead for better latency.
func PersistOpState(ctx context.Context, book *BookState, op OpType) error {
	cfg, ok := OpRegistry[op]
	if !ok {
		return fmt.Errorf("PersistOpState: unknown operation: %s", op)
	}
	state := book.OpGetState(op)
	docID := cfg.DocIDSource(book)
	if docID == "" {
		return nil // No document yet (e.g., no ToC record)
	}
	writeOp := defra.WriteOp{
		Collection: cfg.Collection,
		DocID:      docID,
		Document: map[string]any{
			cfg.FieldPrefix + "_started":  state.IsStarted(),
			cfg.FieldPrefix + "_complete": state.IsComplete(),
			cfg.FieldPrefix + "_failed":   state.IsFailed(),
			cfg.FieldPrefix + "_retries":  state.GetRetries(),
		},
		Op: defra.OpUpdate,
	}
	_, err := SendTracked(ctx, book, writeOp)
	return err
}

// PersistOpStateAsync fires and forgets operation state to DefraDB.
// Delegates to BookState.PersistOpStateAsync for fire-and-forget behavior.
func PersistOpStateAsync(ctx context.Context, book *BookState, op OpType) {
	if book == nil {
		return
	}
	book.PersistOpStateAsync(ctx, op)
}

// PersistBookStatus persists book status to DefraDB and updates CID tracking.
//
// Deprecated: Use PersistBookStatusAsync instead for better latency.
func PersistBookStatus(ctx context.Context, book *BookState, status string) (string, error) {
	if book == nil {
		return "", fmt.Errorf("book is nil")
	}
	result, err := SendTracked(ctx, book, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"status":        status,
			"status_reason": "",
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}
	return result.CID, nil
}

// PersistBookStatusAsync fires and forgets book status to DefraDB.
// Delegates to BookState.PersistBookStatusAsync for fire-and-forget behavior.
func PersistBookStatusAsync(ctx context.Context, book *BookState, status string) {
	if book == nil {
		return
	}
	book.PersistBookStatusAsync(ctx, status)
}

// PersistStructurePhaseAsync fires and forgets structure phase to DefraDB.
// Delegates to BookState.PersistStructurePhaseAsync for fire-and-forget behavior.
func PersistStructurePhaseAsync(ctx context.Context, book *BookState) {
	if book == nil {
		return
	}
	book.PersistStructurePhaseAsync(ctx)
}

// PersistFinalizePhaseAsync fires and forgets finalize phase to ToC.
// Delegates to BookState.PersistFinalizePhaseAsync for fire-and-forget behavior.
func PersistFinalizePhaseAsync(ctx context.Context, book *BookState, phase string) {
	if book == nil {
		return
	}
	book.PersistFinalizePhaseAsync(ctx, phase)
}

// PersistFinalizeProgressAsync fires and forgets finalize progress counters to Book.
// Delegates to BookState.PersistFinalizeProgressAsync for fire-and-forget behavior.
func PersistFinalizeProgressAsync(ctx context.Context, book *BookState) {
	if book == nil {
		return
	}
	book.PersistFinalizeProgressAsync(ctx)
}

// PersistTocLinkProgressAsync fires and forgets toc link progress counters to Book.
// Delegates to BookState.PersistTocLinkProgressAsync for fire-and-forget behavior.
func PersistTocLinkProgressAsync(ctx context.Context, book *BookState) {
	if book == nil {
		return
	}
	book.PersistTocLinkProgressAsync(ctx)
}
