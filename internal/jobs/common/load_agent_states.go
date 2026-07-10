package common

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadAgentStates loads all agent state records for a book from DefraDB.
// This is used for job resume - restoring agent state after a crash.
func LoadAgentStates(ctx context.Context, book *BookState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: "%s"}}) {
			_docID
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
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		if logger != nil {
			logger.Debug("no agent states found", "book_id", book.BookID)
		}
		return nil
	}

	loaded := make([]*AgentState, 0, len(states))
	for _, s := range states {
		data, ok := s.(map[string]any)
		if !ok {
			continue
		}

		state := &AgentState{}

		if docID, ok := data["_docID"].(string); ok {
			state.DocID = docID
		}
		if agentID, ok := data["agent_id"].(string); ok {
			state.AgentID = agentID
		}
		if agentType, ok := data["agent_type"].(string); ok {
			state.AgentType = agentType
		}
		if entryDocID, ok := data["entry_doc_id"].(string); ok {
			state.EntryDocID = entryDocID
		}
		if iteration, ok := data["iteration"].(float64); ok {
			state.Iteration = int(iteration)
		}
		if complete, ok := data["complete"].(bool); ok {
			state.Complete = complete
		}
		if messagesJSON, ok := data["messages_json"].(string); ok {
			state.MessagesJSON = messagesJSON
		}
		if pendingToolCalls, ok := data["pending_tool_calls"].(string); ok {
			state.PendingToolCalls = pendingToolCalls
		}
		if toolResults, ok := data["tool_results"].(string); ok {
			state.ToolResults = toolResults
		}
		if resultJSON, ok := data["result_json"].(string); ok {
			state.ResultJSON = resultJSON
		}

		if state.AgentType != "" {
			loaded = append(loaded, state)
		}
	}

	resumeStates, staleDocIDs := selectAgentStatesForResume(loaded)
	for _, state := range resumeStates {
		book.SetAgentState(state)
	}
	pruneLoadedAgentStates(ctx, defraClient, staleDocIDs, logger)

	if logger != nil {
		logger.Debug("loaded agent states",
			"book_id", book.BookID,
			"stored_count", len(loaded),
			"logical_count", len(book.agentStates),
			"stale_count", len(staleDocIDs))
	}

	return nil
}

// selectAgentStatesForResume collapses historical rows to one incomplete state
// per logical agent. Completed states are cleanup residue and cannot emit more
// work. For duplicates, prefer the most advanced iteration and then a stable
// DocID tie-break so every restart selects the same conversation.
func selectAgentStatesForResume(states []*AgentState) ([]*AgentState, []string) {
	selected := make(map[string]*AgentState)
	stale := make([]string, 0)

	for _, state := range states {
		if state == nil || state.AgentType == "" {
			continue
		}
		if state.Complete {
			if state.DocID != "" {
				stale = append(stale, state.DocID)
			}
			continue
		}

		key := AgentStateKey(state.AgentType, state.EntryDocID)
		current := selected[key]
		if current == nil || agentStatePreferredForResume(state, current) {
			if current != nil && current.DocID != "" {
				stale = append(stale, current.DocID)
			}
			selected[key] = state
		} else if state.DocID != "" {
			stale = append(stale, state.DocID)
		}
	}

	keys := make([]string, 0, len(selected))
	for key := range selected {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	resume := make([]*AgentState, 0, len(keys))
	for _, key := range keys {
		resume = append(resume, selected[key])
	}
	sort.Strings(stale)
	return resume, stale
}

func agentStatePreferredForResume(candidate, current *AgentState) bool {
	if candidate.Iteration != current.Iteration {
		return candidate.Iteration > current.Iteration
	}
	if len(candidate.MessagesJSON) != len(current.MessagesJSON) {
		return len(candidate.MessagesJSON) > len(current.MessagesJSON)
	}
	return candidate.DocID < current.DocID
}

// pruneLoadedAgentStates is best-effort: stale rows must not make a healthy job
// fail to resume. Deterministic selection above preserves correctness even when
// DefraDB cleanup is temporarily unavailable.
func pruneLoadedAgentStates(ctx context.Context, client *defra.Client, docIDs []string, logger interface {
	Warn(msg string, args ...any)
	Info(msg string, args ...any)
}) {
	if len(docIDs) == 0 {
		return
	}

	ops := make([]defra.WriteOp, 0, len(docIDs))
	for _, docID := range docIDs {
		if docID == "" {
			continue
		}
		ops = append(ops, defra.WriteOp{Collection: "AgentState", DocID: docID, Op: defra.OpDelete})
	}
	if len(ops) == 0 {
		return
	}

	failed := 0
	if sink := svcctx.DefraSinkFrom(ctx); sink != nil {
		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			failed = len(ops)
		} else {
			for _, result := range results {
				if result.Err != nil {
					failed++
				}
			}
		}
	} else {
		for _, op := range ops {
			if err := client.Delete(ctx, op.Collection, op.DocID); err != nil {
				failed++
			}
		}
	}

	if failed > 0 {
		if logger != nil {
			logger.Warn("failed to prune some stale agent states",
				"attempted", len(ops), "failed", failed)
		}
		return
	}
	if logger != nil {
		logger.Info("pruned stale agent states", "count", len(ops))
	}
}
