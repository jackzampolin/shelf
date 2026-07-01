package common

import (
	"context"
	"fmt"
	"strings"
	"sync"

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

// --- Agent State Persistence ---

// PersistAgentState idempotently upserts an agent state record in DefraDB,
// keyed on the agent's UUID (agent_id). This is synchronous to capture
// DocID/CID for tracking. Because it is an upsert, re-entering the link stage
// or re-saving the same agent's state updates the existing record instead of
// colliding on DefraDB's stable docID ("a document with the given ID already
// exists").
func PersistAgentState(ctx context.Context, book *BookState, state *AgentState) error {
	if book == nil {
		return fmt.Errorf("book is nil")
	}

	store := book.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
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
		"_bookID":            book.BookID,
	}

	// Idempotent upsert keyed on agent_id (UUID unique per agent).
	// createInput and updateInput are both the full agent-state doc.
	filter := map[string]any{"agent_id": state.AgentID}
	result, err := store.UpsertWithVersion(ctx, "AgentState", filter, doc, doc)
	if err != nil {
		return err
	}
	if result.DocID != "" {
		state.DocID = result.DocID
	}
	if result.CID != "" {
		state.CID = result.CID
	}
	// Store in memory and track the CID (SetAgentState also trackCIDLocked).
	book.SetAgentState(state)
	return nil
}

// PersistAgentStates idempotently upserts multiple agent state records in
// DefraDB, each keyed on its own agent_id (UUID unique per agent). Like
// PersistAgentState this is safe to re-run: existing records are updated
// instead of colliding on DefraDB's stable docID. Upserts run with bounded
// concurrency (mirroring PersistTocEntries) since each upsert is a
// query-then-write rather than a single batch mutation.
func PersistAgentStates(ctx context.Context, book *BookState, states []*AgentState) error {
	if book == nil {
		return fmt.Errorf("book is nil")
	}
	if len(states) == 0 {
		return nil
	}

	store := book.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	type upsertResult struct {
		index int
		docID string
		cid   string
		err   error
	}

	results := make(chan upsertResult, len(states))
	sem := make(chan struct{}, maxConcurrentTocWrites)
	var wg sync.WaitGroup

	for i, state := range states {
		wg.Add(1)
		go func(idx int, st *AgentState) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results <- upsertResult{index: idx, err: fmt.Errorf("panic at index %d: %v", idx, r)}
				}
			}()

			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				results <- upsertResult{index: idx, err: ctx.Err()}
				return
			}

			doc := map[string]any{
				"agent_id":           st.AgentID,
				"agent_type":         st.AgentType,
				"entry_doc_id":       st.EntryDocID,
				"iteration":          st.Iteration,
				"complete":           st.Complete,
				"messages_json":      st.MessagesJSON,
				"pending_tool_calls": st.PendingToolCalls,
				"tool_results":       st.ToolResults,
				"result_json":        st.ResultJSON,
				"_bookID":            book.BookID,
			}

			filter := map[string]any{"agent_id": st.AgentID}
			res, err := store.UpsertWithVersion(ctx, "AgentState", filter, doc, doc)
			if err != nil {
				results <- upsertResult{index: idx, err: fmt.Errorf("agent state %d (%s): %w", idx, st.AgentID, err)}
				return
			}
			results <- upsertResult{index: idx, docID: res.DocID, cid: res.CID}
		}(i, state)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	resultSlice := make([]upsertResult, len(states))
	var errs []string
	for r := range results {
		if r.err != nil {
			errs = append(errs, r.err.Error())
		}
		resultSlice[r.index] = r
	}

	if len(errs) > 0 {
		return fmt.Errorf("failed to persist %d agent states: %s", len(errs), strings.Join(errs, "; "))
	}

	// All succeeded - update states with DocID/CID and store in memory.
	for i, r := range resultSlice {
		if r.docID != "" {
			states[i].DocID = r.docID
		}
		if r.cid != "" {
			states[i].CID = r.cid
		}
		// SetAgentState stores in memory and tracks the CID.
		book.SetAgentState(states[i])
	}

	return nil
}

// DeleteAgentStateByAgentIDAsync removes an agent state record asynchronously.
// This is fire-and-forget - errors are logged but not returned.
// Use this for non-critical cleanup where latency matters more than guaranteed deletion.
func DeleteAgentStateByAgentIDAsync(ctx context.Context, agentID string) {
	if agentID == "" {
		return
	}

	// Run in background to avoid blocking the critical path. Use WithoutCancel so
	// the goroutine keeps the svcctx values (e.g. the defra client) from the parent
	// ctx but is detached from its cancellation — context.Background() dropped the
	// client, causing "defra client not in context" cleanup failures.
	bgCtx := context.WithoutCancel(ctx)
	go func() {
		if err := DeleteAgentStateByAgentID(bgCtx, agentID); err != nil {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Warn("async agent state cleanup failed (orphaned record may remain)",
					"agent_id", agentID,
					"error", err)
			}
		}
	}()
}

// DeleteAgentStateByAgentID removes an agent state record by querying for agent_id.
// This is used when we don't have the DocID (e.g., after async creates).
// Uses sync delete to ensure records are actually deleted (prevents orphaned records).
// Prefer DeleteAgentStateByAgentIDAsync for non-critical cleanup paths.
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

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("DeleteAgentStateByAgentID: defra sink not in context")
	}

	ops := make([]defra.WriteOp, 0, len(states))
	// Delete each match (should be at most one, but handle multiple defensively).
	for _, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "AgentState",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	if len(ops) == 0 {
		return nil
	}

	results, err := sink.SendManySync(ctx, ops)
	if err != nil {
		return fmt.Errorf("DeleteAgentStateByAgentID: batch delete failed for agent %s: %w", agentID, err)
	}
	for _, result := range results {
		if result.Err != nil {
			return fmt.Errorf("DeleteAgentStateByAgentID: failed to delete doc %s for agent %s: %w", result.DocID, agentID, result.Err)
		}
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
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("DeleteAgentStatesForType: defra sink not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query agent states for this book and type
	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: "%s"}, agent_type: {_eq: "%s"}}) {
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

	var skippedCount int
	ops := make([]defra.WriteOp, 0, len(states))
	for i, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			skippedCount++
			if logger != nil {
				logger.Warn("unexpected data type while deleting agent states by type",
					"book_id", bookID, "agent_type", agentType, "index", i)
			}
			continue
		}

		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			skippedCount++
			continue
		}

		ops = append(ops, defra.WriteOp{
			Collection: "AgentState",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	if len(ops) > 0 {
		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("DeleteAgentStatesForType: batch delete failed: %w", err)
		}
		for _, result := range results {
			if result.Err != nil {
				return fmt.Errorf("DeleteAgentStatesForType: failed to delete %s: %w", result.DocID, result.Err)
			}
		}
	}

	deletedCount := len(ops)
	if logger != nil && deletedCount > 0 {
		logger.Debug("deleted agent states for type",
			"book_id", bookID, "agent_type", agentType, "count", deletedCount)
	}

	return nil
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
