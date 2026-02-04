package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

// PersistNewAgentState creates an agent state record and adds to b.agentStates.
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
		"book_id":            b.BookID,
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "AgentState",
		Document:   doc,
		Op:         defra.OpCreate,
	})
	if err != nil {
		return fmt.Errorf("failed to create agent state: %w", err)
	}

	// Update state with DocID/CID
	state.DocID = result.DocID
	state.CID = result.CID

	// Add to memory
	b.SetAgentState(state)

	return nil
}

// PersistNewAgentStates batch-creates agent state records and adds all to b.agentStates.
func (b *BookState) PersistNewAgentStates(ctx context.Context, states []*AgentState) error {
	if len(states) == 0 {
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Build write operations
	ops := make([]defra.WriteOp, len(states))
	for i, state := range states {
		ops[i] = defra.WriteOp{
			Collection: "AgentState",
			Document: map[string]any{
				"agent_id":           state.AgentID,
				"agent_type":         state.AgentType,
				"entry_doc_id":       state.EntryDocID,
				"iteration":          state.Iteration,
				"complete":           state.Complete,
				"messages_json":      state.MessagesJSON,
				"pending_tool_calls": state.PendingToolCalls,
				"tool_results":       state.ToolResults,
				"result_json":        state.ResultJSON,
				"book_id":            b.BookID,
			},
			Op: defra.OpCreate,
		}
	}

	// Batch create
	results, err := store.SendManySync(ctx, ops)
	if err != nil {
		return fmt.Errorf("failed to create agent states: %w", err)
	}

	// Update states with DocID/CID and add to memory
	for i, result := range results {
		if i < len(states) {
			states[i].DocID = result.DocID
			states[i].CID = result.CID
			b.SetAgentState(states[i])
		}
	}

	return nil
}

// DeleteAgentStateByKeys deletes an agent state record and removes from b.agentStates.
func (b *BookState) DeleteAgentStateByKeys(ctx context.Context, agentType, entryDocID string) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Get from memory first
	state := b.GetAgentState(agentType, entryDocID)
	if state == nil {
		return nil // Not found, nothing to delete
	}

	if state.DocID != "" {
		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "AgentState",
			DocID:      state.DocID,
			Op:         defra.OpDelete,
		})
		if err != nil {
			return fmt.Errorf("failed to delete agent state: %w", err)
		}
	}

	// Remove from memory
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
		AgentState(filter: {book_id: {_eq: "%s"}, agent_type: {_eq: "%s"}}) {
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
		AgentState(filter: {book_id: {_eq: "%s"}}) {
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
