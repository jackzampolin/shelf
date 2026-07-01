package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

// PersistNewAgentState idempotently upserts an agent state record (keyed on the
// agent's UUID agent_id) and adds it to b.agentStates. Using an upsert keeps the
// call safe to re-run: an existing record is updated instead of colliding on
// DefraDB's stable docID.
func (b *BookState) PersistNewAgentState(ctx context.Context, state *AgentState) error {
	store := b.getStore(ctx)
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
		"_bookID":            b.BookID,
	}

	filter := map[string]any{"agent_id": state.AgentID}
	result, err := store.UpsertWithVersion(ctx, "AgentState", filter, doc, doc)
	if err != nil {
		return fmt.Errorf("failed to upsert agent state: %w", err)
	}

	// Update state with DocID/CID
	state.DocID = result.DocID
	state.CID = result.CID

	// Add to memory
	b.SetAgentState(state)

	return nil
}

// PersistNewAgentStates idempotently upserts agent state records (each keyed on
// its own agent_id UUID) and adds them all to b.agentStates. Each state is
// upserted individually so re-runs update existing records instead of colliding
// on DefraDB's stable docID.
func (b *BookState) PersistNewAgentStates(ctx context.Context, states []*AgentState) error {
	if len(states) == 0 {
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	for _, state := range states {
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
			"_bookID":            b.BookID,
		}

		filter := map[string]any{"agent_id": state.AgentID}
		result, err := store.UpsertWithVersion(ctx, "AgentState", filter, doc, doc)
		if err != nil {
			return fmt.Errorf("failed to upsert agent state %s: %w", state.AgentID, err)
		}

		state.DocID = result.DocID
		state.CID = result.CID
		b.SetAgentState(state)
	}

	return nil
}

// DeleteAgentStateByKeys deletes all matching agent state records and removes
// the logical state from b.agentStates.
func (b *BookState) DeleteAgentStateByKeys(ctx context.Context, agentType, entryDocID string) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	if err := defra.ValidateID(b.BookID); err != nil {
		return fmt.Errorf("invalid book ID: %w", err)
	}
	if err := defra.ValidateID(agentType); err != nil {
		return fmt.Errorf("invalid agent type: %w", err)
	}
	if entryDocID != "" {
		if err := defra.ValidateID(entryDocID); err != nil {
			return fmt.Errorf("invalid entry doc ID: %w", err)
		}
	}

	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: "%s"}, agent_type: {_eq: "%s"}, entry_doc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, b.BookID, agentType, entryDocID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if ok && len(states) > 0 {
		ops := make([]defra.WriteOp, 0, len(states))
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

		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to delete agent states: %w", err)
		}
		for _, result := range results {
			if result.Err != nil {
				return fmt.Errorf("failed to delete agent state %s: %w", result.DocID, result.Err)
			}
		}
	} else {
		// Older in-memory-only test paths may have a state without a matching
		// store row. Fall back to its doc ID if present.
		state := b.GetAgentState(agentType, entryDocID)
		if state != nil && state.DocID != "" {
			if _, err := store.SendSync(ctx, defra.WriteOp{
				Collection: "AgentState",
				DocID:      state.DocID,
				Op:         defra.OpDelete,
			}); err != nil {
				return fmt.Errorf("failed to delete agent state: %w", err)
			}
		}
	}

	// Remove from memory even when no persisted state exists.
	b.RemoveAgentState(agentType, entryDocID)

	return nil
}

// DeleteAgentStatesForType deletes all agent states of a type and clears from b.agentStates.
func (b *BookState) DeleteAgentStatesForType(ctx context.Context, agentType string) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Query for all agent states of this type for this book
	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: "%s"}, agent_type: {_eq: "%s"}}) {
			_docID
		}
	}`, b.BookID, agentType)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		// No DB records, just clear memory
		b.ClearAgentStates(agentType)
		return nil
	}

	// Collect delete ops
	var ops []defra.WriteOp
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

	// Batch delete
	if len(ops) > 0 {
		_, err = store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to delete agent states: %w", err)
		}
	}

	// Clear from memory
	b.ClearAgentStates(agentType)

	return nil
}

// DeleteAllAgentStates deletes all agent states for this book and clears b.agentStates entirely.
func (b *BookState) DeleteAllAgentStates(ctx context.Context) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Query for all agent states for this book
	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: "%s"}}) {
			_docID
		}
	}`, b.BookID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		// No DB records, just clear memory
		b.mu.Lock()
		b.agentStates = make(map[string]*AgentState)
		b.mu.Unlock()
		return nil
	}

	// Collect delete ops
	var ops []defra.WriteOp
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

	// Batch delete
	if len(ops) > 0 {
		_, err = store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to delete agent states: %w", err)
		}
	}

	// Clear all from memory
	b.mu.Lock()
	b.agentStates = make(map[string]*AgentState)
	b.mu.Unlock()

	return nil
}
