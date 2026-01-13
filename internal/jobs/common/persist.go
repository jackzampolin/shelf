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
// Note: This is fire-and-forget. Use SendToSinkSync for critical operations.
func SendToSink(ctx context.Context, op defra.WriteOp) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}
	sink.Send(op)
	return nil
}

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

// --- Agent State Persistence ---

// PersistAgentState creates or updates an agent state record in DefraDB.
// Returns the document ID (existing or newly created).
func PersistAgentState(ctx context.Context, bookID string, state *AgentState) (string, error) {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return "", fmt.Errorf("defra sink not in context")
	}

	doc := map[string]any{
		"agent_id":            state.AgentID,
		"agent_type":          state.AgentType,
		"entry_doc_id":        state.EntryDocID,
		"iteration":           state.Iteration,
		"complete":            state.Complete,
		"messages_json":       state.MessagesJSON,
		"pending_tool_calls":  state.PendingToolCalls,
		"tool_results":        state.ToolResults,
		"result_json":         state.ResultJSON,
		"book_id":             bookID,
	}

	if state.DocID != "" {
		// Update existing
		sink.Send(defra.WriteOp{
			Collection: "AgentState",
			DocID:      state.DocID,
			Document:   doc,
			Op:         defra.OpUpdate,
		})
		return state.DocID, nil
	}

	// Create new - need sync to get DocID back
	result, err := sink.SendSync(ctx, defra.WriteOp{
		Collection: "AgentState",
		Document:   doc,
		Op:         defra.OpCreate,
	})
	if err != nil {
		return "", fmt.Errorf("failed to create agent state: %w", err)
	}
	return result.DocID, nil
}

// DeleteAgentState removes an agent state record from DefraDB.
func DeleteAgentState(ctx context.Context, docID string) error {
	if docID == "" {
		return nil
	}
	return SendToSink(ctx, defra.WriteOp{
		Collection: "AgentState",
		DocID:      docID,
		Op:         defra.OpDelete,
	})
}

// DeleteAgentStatesForBook removes all agent state records for a book.
// This is used when resetting operations or cleaning up completed jobs.
func DeleteAgentStatesForBook(ctx context.Context, bookID string) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Query all agent states for this book
	query := fmt.Sprintf(`{
		AgentState(filter: {book_id: {_eq: "%s"}}) {
			_docID
		}
	}`, bookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		return nil
	}

	// Delete each one
	for _, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			continue
		}
		docID, _ := state["_docID"].(string)
		if docID != "" {
			if err := DeleteAgentState(ctx, docID); err != nil {
				return err
			}
		}
	}

	return nil
}

// --- Synchronous Persist Functions ---
// Use these for critical state transitions to ensure writes complete before proceeding.

// PersistBookStatusSync persists book status and waits for confirmation.
func PersistBookStatusSync(ctx context.Context, bookID string, status string) error {
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      bookID,
		Document: map[string]any{
			"status": status,
		},
		Op: defra.OpUpdate,
	})
}

// PersistStructureStateSync persists structure operation state and waits for confirmation.
func PersistStructureStateSync(ctx context.Context, bookID string, op *OperationState) error {
	return SendToSinkSync(ctx, defra.WriteOp{
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

// PersistTocFinalizeStateSync persists ToC finalize operation state and waits for confirmation.
func PersistTocFinalizeStateSync(ctx context.Context, tocDocID string, op *OperationState) error {
	if tocDocID == "" {
		return nil // No ToC record yet
	}
	return SendToSinkSync(ctx, defra.WriteOp{
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

// PersistStructurePhaseSync persists structure phase tracking data and waits for confirmation.
func PersistStructurePhaseSync(ctx context.Context, book *BookState) error {
	total, extracted, polished, failed := book.GetStructureProgress()
	return SendToSinkSync(ctx, defra.WriteOp{
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
