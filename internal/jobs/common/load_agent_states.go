package common

import (
	"context"
	"fmt"

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
			book.SetAgentState(state)
		}
	}

	if logger != nil {
		logger.Debug("loaded agent states",
			"book_id", book.BookID,
			"count", len(book.agentStates))
	}

	return nil
}
