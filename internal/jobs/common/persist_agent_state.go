package common

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

const (
	maxAgentStateWriteAttempts = 4
	agentStateWriteRetryDelay  = 75 * time.Millisecond
)

// --- Agent State Persistence ---

// PersistAgentState idempotently upserts an agent state record in DefraDB,
// keyed on the book and agent ID. This is synchronous to capture
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

	// Agent IDs are stable tracing keys, not globally unique UUIDs. Scope the
	// filter to the owning book so one book can never resume or overwrite another
	// book's agent state.
	// createInput and updateInput are both the full agent-state doc.
	filter := map[string]any{"_bookID": book.BookID, "agent_id": state.AgentID}
	// DefraDB v1.0.0-rc1's generic upsert planner can return an empty HTTP 500
	// when updating a large existing String field. Agent checkpoints normally
	// have the prior row in BookState, so use the stable docID update mutation
	// for multi-turn updates and reserve upsert for initial creation/recovery.
	existing := book.GetAgentState(state.AgentType, state.EntryDocID)
	existingDocID := state.DocID
	if existingDocID == "" && existing != nil && existing.AgentID == state.AgentID {
		existingDocID = existing.DocID
	}
	var result defra.WriteResult
	var err error
	if existingDocID != "" {
		result, err = updateAgentStateWithRetry(ctx, store, existingDocID, filter, doc)
	} else {
		result, err = upsertAgentStateWithRetry(ctx, store, filter, doc)
	}
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
// DefraDB, each keyed on its owning book and agent ID. Like
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

			filter := map[string]any{"_bookID": book.BookID, "agent_id": st.AgentID}
			existingDocID := st.DocID
			if existingDocID == "" {
				existing := book.GetAgentState(st.AgentType, st.EntryDocID)
				if existing != nil && existing.AgentID == st.AgentID {
					existingDocID = existing.DocID
				}
			}
			var res defra.WriteResult
			var err error
			if existingDocID != "" {
				res, err = updateAgentStateWithRetry(ctx, store, existingDocID, filter, doc)
			} else {
				res, err = upsertAgentStateWithRetry(ctx, store, filter, doc)
			}
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

func upsertAgentStateWithRetry(ctx context.Context, store StateStore, filter, doc map[string]any) (defra.WriteResult, error) {
	return writeAgentStateWithRetry(ctx, store, "", filter, doc)
}

func updateAgentStateWithRetry(ctx context.Context, store StateStore, docID string, filter, doc map[string]any) (defra.WriteResult, error) {
	if docID == "" {
		return defra.WriteResult{}, fmt.Errorf("agent state update requires docID")
	}
	return writeAgentStateWithRetry(ctx, store, docID, filter, doc)
}

func writeAgentStateWithRetry(ctx context.Context, store StateStore, docID string, filter, doc map[string]any) (defra.WriteResult, error) {
	var lastErr error
	for attempt := 1; attempt <= maxAgentStateWriteAttempts; attempt++ {
		var result defra.WriteResult
		var err error
		if docID == "" {
			result, err = store.UpsertWithVersion(ctx, "AgentState", filter, doc, doc)
		} else {
			result, err = store.UpdateWithVersion(ctx, "AgentState", docID, doc)
		}
		if err == nil {
			return result, nil
		}
		lastErr = err
		if !isTransientAgentStateWriteError(err) {
			break
		}
		// DefraDB can commit an upsert and then return an empty HTTP 500 while
		// assembling the response. Read the row back before retrying so a
		// post-commit transport failure is treated as success, but an older row
		// with the same stable identity is not.
		if recovered, ok := verifyAgentStateWrite(ctx, store, filter, doc); ok {
			return recovered, nil
		}
		if attempt == maxAgentStateWriteAttempts {
			break
		}
		delay := agentStateWriteRetryDelay * time.Duration(attempt)
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return defra.WriteResult{}, ctx.Err()
		case <-timer.C:
		}
	}
	operation := "upsert"
	if docID != "" {
		operation = "update"
	}
	return defra.WriteResult{}, fmt.Errorf("agent state %s failed after %d attempts: %w", operation, maxAgentStateWriteAttempts, lastErr)
}

func verifyAgentStateWrite(ctx context.Context, store StateStore, filter, wanted map[string]any) (defra.WriteResult, bool) {
	bookID, bookOK := filter["_bookID"].(string)
	agentID, agentOK := filter["agent_id"].(string)
	if !bookOK || !agentOK || bookID == "" || agentID == "" {
		return defra.WriteResult{}, false
	}
	bookGQL, err := json.Marshal(bookID)
	if err != nil {
		return defra.WriteResult{}, false
	}
	agentGQL, err := json.Marshal(agentID)
	if err != nil {
		return defra.WriteResult{}, false
	}
	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: %s}, agent_id: {_eq: %s}}) {
			_docID
			_version { cid }
			_bookID
			agent_id
			agent_type
			entry_doc_id
			iteration
			complete
			messages_json
			pending_tool_calls
			tool_results
			result_json
		}
	}`, bookGQL, agentGQL)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil || resp == nil || resp.Error() != "" {
		return defra.WriteResult{}, false
	}
	docs, ok := resp.Data["AgentState"].([]any)
	if !ok {
		return defra.WriteResult{}, false
	}
	for _, raw := range docs {
		doc, ok := raw.(map[string]any)
		if !ok || !agentStateDocumentMatches(doc, wanted) {
			continue
		}
		docID, _ := doc["_docID"].(string)
		if docID != "" {
			result := defra.WriteResult{DocID: docID}
			if versions, ok := doc["_version"].([]any); ok {
				for _, rawVersion := range versions {
					version, ok := rawVersion.(map[string]any)
					if !ok {
						continue
					}
					if cid, ok := version["cid"].(string); ok && cid != "" {
						result.CIDs = append(result.CIDs, cid)
					}
				}
			}
			if len(result.CIDs) > 0 {
				result.CID = result.CIDs[0]
			}
			return result, true
		}
	}
	return defra.WriteResult{}, false
}

func agentStateDocumentMatches(got, wanted map[string]any) bool {
	for _, field := range []string{
		"_bookID", "agent_id", "agent_type", "entry_doc_id", "messages_json",
		"pending_tool_calls", "tool_results", "result_json",
	} {
		gotValue, gotOK := got[field].(string)
		wantValue, wantOK := wanted[field].(string)
		if !gotOK || !wantOK || gotValue != wantValue {
			return false
		}
	}
	gotComplete, gotOK := got["complete"].(bool)
	wantComplete, wantOK := wanted["complete"].(bool)
	if !gotOK || !wantOK || gotComplete != wantComplete {
		return false
	}
	wantIteration, ok := wanted["iteration"].(int)
	if !ok {
		return false
	}
	switch gotIteration := got["iteration"].(type) {
	case int:
		return gotIteration == wantIteration
	case int64:
		return gotIteration == int64(wantIteration)
	case float64:
		return gotIteration == float64(wantIteration)
	default:
		return false
	}
}

func isTransientAgentStateWriteError(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "status 500") ||
		strings.Contains(msg, "transaction conflict") ||
		strings.Contains(msg, "context deadline exceeded") ||
		strings.Contains(msg, "connection reset") ||
		strings.Contains(msg, "unexpected eof") ||
		strings.Contains(msg, "document with the given id already exists") ||
		strings.Contains(msg, "document with given id already exists")
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
