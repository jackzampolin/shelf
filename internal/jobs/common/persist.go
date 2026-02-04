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
		results = make([]defra.WriteResult, len(ops))
		for i, op := range ops {
			results[i], err = book.Store.SendSync(ctx, op)
			if err != nil {
				return results, err
			}
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

// PersistBookStatus persists book status to DefraDB and updates CID tracking.
func PersistBookStatus(ctx context.Context, book *BookState, status string) (string, error) {
	if book == nil {
		return "", fmt.Errorf("book is nil")
	}
	result, err := SendTracked(ctx, book, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"status": status,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}
	return result.CID, nil
}

// PersistStructurePhase persists structure phase tracking data from BookState to DefraDB.
func PersistStructurePhase(ctx context.Context, book *BookState) error {
	total, extracted, polished, failed := book.GetStructureProgress()
	_, err := SendTracked(ctx, book, defra.WriteOp{
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
	return err
}

// --- Agent State Persistence ---

// PersistAgentState creates an agent state record in DefraDB.
// This is synchronous to capture DocID/CID for tracking.
// Only call this once at agent creation, not during the agent loop.
func PersistAgentState(ctx context.Context, book *BookState, state *AgentState) error {
	if book == nil {
		return fmt.Errorf("book is nil")
	}

	doc := map[string]any{
		"agent_id":           state.AgentID,
		"agent_type":         state.AgentType,
		"entry_doc_id":       state.EntryDocID,
		"iteration":          state.Iteration,
		"complete":           state.Complete,
		"messages_json":      state.MessagesJSON,
		"pending_tool_calls": state.PendingToolCalls,
		"tool_results":       state.ToolResults,
		"result_json":        state.ResultJSON,
		"book_id":            book.BookID,
	}

	// Synchronous create to capture DocID/CID
	result, err := SendTracked(ctx, book, defra.WriteOp{
		Collection: "AgentState",
		Document:   doc,
		Op:         defra.OpCreate,
	})
	if err != nil {
		return err
	}
	if result.DocID != "" {
		state.DocID = result.DocID
	}
	if result.CID != "" {
		state.CID = result.CID
	}
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

// PersistFinalizePhase persists finalize phase tracking to ToC.
func PersistFinalizePhase(ctx context.Context, book *BookState, phase string) (string, error) {
	if book == nil {
		return "", fmt.Errorf("book is nil")
	}
	tocDocID := book.TocDocID()
	if tocDocID == "" {
		return "", nil
	}
	result, err := SendTracked(ctx, book, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"finalize_phase": phase,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}
	return result.CID, nil
}

// PersistFinalizeProgress persists finalize progress counters to Book.
func PersistFinalizeProgress(ctx context.Context, book *BookState) error {
	entriesComplete, entriesFound, gapsComplete, gapsFixes := book.GetFinalizeProgress()
	_, err := SendTracked(ctx, book, defra.WriteOp{
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
	return err
}

// PersistTocLinkProgress persists toc link progress counters to Book.
func PersistTocLinkProgress(ctx context.Context, book *BookState) error {
	total, done := book.GetTocLinkProgress()
	_, err := SendTracked(ctx, book, defra.WriteOp{
		Collection: "Book",
		DocID:      book.BookID,
		Document: map[string]any{
			"toc_link_entries_total": total,
			"toc_link_entries_done":  done,
		},
		Op: defra.OpUpdate,
	})
	return err
}
