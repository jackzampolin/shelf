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

// PersistAgentStateAsync creates an agent state record in DefraDB asynchronously.
// This is fire-and-forget - no DocID is returned. Use agent_id for identification.
// Only call this once at agent creation, not during the agent loop.
func PersistAgentStateAsync(ctx context.Context, bookID string, state *AgentState) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
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

	// Fire-and-forget create - use agent_id for later identification
	sink.Send(defra.WriteOp{
		Collection: "AgentState",
		Document:   doc,
		Op:         defra.OpCreate,
	})
	return nil
}

// DeleteAgentState removes an agent state record from DefraDB by DocID.
// Uses synchronous write to ensure deletion completes and prevent orphaned records.
func DeleteAgentState(ctx context.Context, docID string) error {
	if docID == "" {
		return nil
	}
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "AgentState",
		DocID:      docID,
		Op:         defra.OpDelete,
	})
}

// DeleteAgentStateByAgentID removes an agent state record by querying for agent_id.
// This is used when we don't have the DocID (e.g., after async creates).
// Uses async delete for performance - caller should not depend on completion.
func DeleteAgentStateByAgentID(ctx context.Context, agentID string) error {
	if agentID == "" {
		return nil
	}

	// Validate agentID to prevent GraphQL injection
	if err := defra.ValidateID(agentID); err != nil {
		return fmt.Errorf("DeleteAgentStateByAgentID: invalid agent ID: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("DeleteAgentStateByAgentID: defra client not in context")
	}

	// Query for the DocID
	query := fmt.Sprintf(`{
		AgentState(filter: {agent_id: {_eq: "%s"}}) {
			_docID
		}
	}`, agentID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("DeleteAgentStateByAgentID: query failed: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		return nil // Not found, nothing to delete
	}

	// Delete each match (should be at most one, but handle multiple defensively)
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("DeleteAgentStateByAgentID: defra sink not in context")
	}

	for _, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		// Async delete for performance
		sink.Send(defra.WriteOp{
			Collection: "AgentState",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	return nil
}

// DeleteAgentStatesForBook removes all agent state records for a book.
// This is used when resetting operations or cleaning up completed jobs.
// Returns an error if any deletion fails. Logs warnings for malformed records.
func DeleteAgentStatesForBook(ctx context.Context, bookID string) error {
	// Validate bookID to prevent GraphQL injection
	if err := defra.ValidateID(bookID); err != nil {
		return fmt.Errorf("DeleteAgentStatesForBook: invalid book ID: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("DeleteAgentStatesForBook: defra client not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query all agent states for this book
	query := fmt.Sprintf(`{
		AgentState(filter: {book_id: {_eq: "%s"}}) {
			_docID
		}
	}`, bookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("DeleteAgentStatesForBook: failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		return nil
	}

	// Track skipped records for logging
	var skippedCount int
	var deletedCount int

	// Delete each one
	for i, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			skippedCount++
			if logger != nil {
				logger.Warn("DeleteAgentStatesForBook: unexpected data type in result",
					"book_id", bookID,
					"index", i,
					"type", fmt.Sprintf("%T", s))
			}
			continue
		}

		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			skippedCount++
			if logger != nil {
				logger.Warn("DeleteAgentStatesForBook: missing or invalid _docID in agent state",
					"book_id", bookID,
					"index", i,
					"state_data", state)
			}
			continue
		}

		if err := DeleteAgentState(ctx, docID); err != nil {
			return fmt.Errorf("DeleteAgentStatesForBook: failed to delete agent state %s: %w", docID, err)
		}
		deletedCount++
	}

	// Log summary if there were issues
	if skippedCount > 0 && logger != nil {
		logger.Warn("DeleteAgentStatesForBook: some records were skipped",
			"book_id", bookID,
			"deleted", deletedCount,
			"skipped", skippedCount)
	}

	return nil
}

// DeleteAgentStatesForType removes agent state records for a specific agent type and book.
// This is used when resetting a specific operation (e.g., toc_finder) without affecting
// other agent states for the same book.
func DeleteAgentStatesForType(ctx context.Context, bookID, agentType string) error {
	// Validate IDs to prevent GraphQL injection
	if err := defra.ValidateID(bookID); err != nil {
		return fmt.Errorf("DeleteAgentStatesForType: invalid book ID: %w", err)
	}
	if err := defra.ValidateID(agentType); err != nil {
		return fmt.Errorf("DeleteAgentStatesForType: invalid agent type: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("DeleteAgentStatesForType: defra client not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query agent states for this book and type
	query := fmt.Sprintf(`{
		AgentState(filter: {book_id: {_eq: "%s"}, agent_type: {_eq: "%s"}}) {
			_docID
		}
	}`, bookID, agentType)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("DeleteAgentStatesForType: failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		return nil
	}

	var deletedCount, skippedCount int
	for i, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			skippedCount++
			if logger != nil {
				logger.Warn("DeleteAgentStatesForType: unexpected data type",
					"book_id", bookID, "agent_type", agentType, "index", i)
			}
			continue
		}

		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			skippedCount++
			continue
		}

		if err := DeleteAgentState(ctx, docID); err != nil {
			return fmt.Errorf("DeleteAgentStatesForType: failed to delete %s: %w", docID, err)
		}
		deletedCount++
	}

	if logger != nil && deletedCount > 0 {
		logger.Debug("deleted agent states for type",
			"book_id", bookID, "agent_type", agentType, "count", deletedCount)
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

// PersistFinalizePhase persists finalize phase tracking to ToC.
func PersistFinalizePhase(ctx context.Context, tocDocID string, phase string) error {
	if tocDocID == "" {
		return nil
	}
	return SendToSink(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_phase": phase,
		},
		Op: defra.OpUpdate,
	})
}

// PersistFinalizePhaseSync persists finalize phase tracking to ToC and waits for confirmation.
func PersistFinalizePhaseSync(ctx context.Context, tocDocID string, phase string) error {
	if tocDocID == "" {
		return nil
	}
	return SendToSinkSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_phase": phase,
		},
		Op: defra.OpUpdate,
	})
}

// PersistFinalizeProgress persists finalize progress counters to Book.
func PersistFinalizeProgress(ctx context.Context, book *BookState) error {
	entriesComplete, entriesFound, gapsComplete, gapsFixes := book.GetFinalizeProgress()
	return SendToSink(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"finalize_entries_complete": entriesComplete,
			"finalize_entries_found":    entriesFound,
			"finalize_gaps_complete":    gapsComplete,
			"finalize_gaps_fixes":       gapsFixes,
		},
		Op: defra.OpUpdate,
	})
}
