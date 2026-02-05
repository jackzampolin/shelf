package observability

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// AgentRun captures a complete agent execution for debugging.
type AgentRun struct {
	DocID string `json:"_docID,omitempty"`

	// Context
	AgentID   string `json:"agent_id"`
	AgentType string `json:"agent_type"` // "toc_finder", "toc_extract", etc.
	BookID    string `json:"book_id"`
	JobID     string `json:"job_id,omitempty"`

	// Execution
	StartedAt   time.Time `json:"started_at"`
	CompletedAt time.Time `json:"completed_at,omitempty"`
	Iterations  int       `json:"iterations"`
	Status      string    `json:"status"` // "running", "completed", "failed"

	// Result
	Success bool   `json:"success"`
	Error   string `json:"error,omitempty"`

	// Conversation trace (JSON-encoded for flexibility)
	MessagesJSON string `json:"messages_json,omitempty"`

	// Tool calls summary
	ToolCallsJSON string `json:"tool_calls_json,omitempty"`

	// Final result (JSON-encoded)
	ResultJSON string `json:"result_json,omitempty"`
}

// ToolCallLog captures a single tool call for the trace.
type ToolCallLog struct {
	Iteration int       `json:"iteration"`
	Timestamp time.Time `json:"timestamp"`
	ToolName  string    `json:"tool_name"`
	ArgsJSON  string    `json:"args_json"`
	ResultLen int       `json:"result_len"`
	Error     string    `json:"error,omitempty"`
}

// Logger records agent executions to DefraDB.
type Logger struct {
	agentID   string
	agentType string
	bookID    string
	jobID     string
	docID     string // DefraDB document ID for this run

	startedAt time.Time
	toolCalls []ToolCallLog
	messages  []providers.Message
}

// NewLogger creates a new agent logger and persists the initial "running" record.
func NewLogger(ctx context.Context, agentID, agentType, bookID, jobID string) *Logger {
	l := &Logger{
		agentID:   agentID,
		agentType: agentType,
		bookID:    bookID,
		jobID:     jobID,
		startedAt: time.Now(),
		toolCalls: make([]ToolCallLog, 0),
	}

	// Create initial "running" record in DefraDB
	l.saveInitial(ctx)

	return l
}

// saveInitial creates the initial AgentRun record with status="running".
// Uses async Send to avoid blocking agent creation - the final Save() will
// create a complete record if this initial record wasn't created.
func (l *Logger) saveInitial(ctx context.Context) {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		// Log that observability is disabled (sink not available)
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Debug("agent observability disabled: no defra sink in context",
				"agent_id", l.agentID,
				"agent_type", l.agentType)
		}
		return
	}

	// Skip initial record creation - it's not worth the sync overhead.
	// The Save() method will create a complete record at the end.
	// This avoids blocking agent creation when spawning many agents in parallel.
	//
	// Note: We lose real-time "running" status visibility, but gain significant
	// performance when creating many agents (e.g., toc_entry_finder for each ToC entry).
}

// LogToolCall records a tool call.
func (l *Logger) LogToolCall(iteration int, toolName string, args map[string]any, result string, err error) {
	argsJSON, _ := json.Marshal(args)
	errStr := ""
	if err != nil {
		errStr = err.Error()
	}
	l.toolCalls = append(l.toolCalls, ToolCallLog{
		Iteration: iteration,
		Timestamp: time.Now(),
		ToolName:  toolName,
		ArgsJSON:  string(argsJSON),
		ResultLen: len(result),
		Error:     errStr,
	})
}

// UpdateProgress persists the current iteration and tool calls to DefraDB.
// Call this after each iteration to show real-time agent progress.
// Note: Currently disabled (no-op) since we skip initial record creation for performance.
// Progress is only recorded in the final Save() call.
func (l *Logger) UpdateProgress(ctx context.Context, iteration int) {
	// Progress updates are disabled - we create a complete record in Save()
	// to avoid sync overhead during agent execution.
}

// SetMessages captures the final message history.
func (l *Logger) SetMessages(messages []providers.Message) {
	l.messages = messages
}

// Save persists the final agent run state to DefraDB.
// Updates the existing record if one was created at start, otherwise creates a new one.
func (l *Logger) Save(ctx context.Context, success bool, iterations int, result any, err error) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return nil // No sink available, skip logging
	}

	// Serialize messages (truncate content for large messages)
	messagesForLog := make([]map[string]any, 0, len(l.messages))
	for _, m := range l.messages {
		content := m.Content
		if len(content) > 1000 {
			content = content[:1000] + "... [truncated]"
		}
		msgLog := map[string]any{
			"role":    m.Role,
			"content": content,
		}
		if len(m.ToolCalls) > 0 {
			msgLog["tool_calls_count"] = len(m.ToolCalls)
		}
		if m.ToolCallID != "" {
			msgLog["tool_call_id"] = m.ToolCallID
		}
		messagesForLog = append(messagesForLog, msgLog)
	}
	messagesJSON, _ := json.Marshal(messagesForLog)

	// Serialize tool calls
	toolCallsJSON, _ := json.Marshal(l.toolCalls)

	// Serialize result
	var resultJSON []byte
	if result != nil {
		resultJSON, _ = json.Marshal(result)
	}

	// Build error string
	errStr := ""
	if err != nil {
		errStr = err.Error()
	}

	// Determine status
	status := "completed"
	if !success {
		status = "failed"
	}

	run := map[string]any{
		"completed_at":    time.Now().Format(time.RFC3339),
		"iterations":      iterations,
		"success":         success,
		"status":          status,
		"error":           errStr,
		"messages_json":   string(messagesJSON),
		"tool_calls_json": string(toolCallsJSON),
		"result_json":     string(resultJSON),
	}

	// Update existing record if we have a docID, otherwise create new
	if l.docID != "" {
		sink.Send(defra.WriteOp{
			Collection: "AgentRun",
			DocID:      l.docID,
			Document:   run,
			Op:         defra.OpUpdate,
			Source:     "AgentLogger:Save:update",
		})
	} else {
		// Fallback: create new record with all fields
		run["agent_id"] = l.agentID
		run["agent_type"] = l.agentType
		run["book_id"] = l.bookID
		run["job_id"] = l.jobID
		run["started_at"] = l.startedAt.Format(time.RFC3339)
		sink.Send(defra.WriteOp{
			Collection: "AgentRun",
			Document:   run,
			Op:         defra.OpCreate,
			Source:     "AgentLogger:Save:create",
		})
	}

	return nil
}

// Schema returns the DefraDB schema for agent observability.
const Schema = `
type AgentRun {
	agent_id: String @index
	agent_type: String @index
	book_id: String @index
	job_id: String @index
	started_at: DateTime
	completed_at: DateTime
	iterations: Int
	status: String @index
	success: Boolean
	error: String
	messages_json: String
	tool_calls_json: String
	result_json: String
}
`

// Query helpers for retrieving agent runs.

// ListAgentRuns returns recent agent runs for a book.
func ListAgentRuns(ctx context.Context, bookID string, limit int) ([]AgentRun, error) {
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		AgentRun(filter: {book_id: {_eq: "%s"}}, order: {started_at: DESC}, limit: %d) {
			_docID
			agent_id
			agent_type
			book_id
			job_id
			started_at
			completed_at
			iterations
			status
			success
			error
			messages_json
			tool_calls_json
			result_json
		}
	}`, bookID, limit)

	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}

	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query error: %s", errMsg)
	}

	runs := make([]AgentRun, 0)
	if data, ok := resp.Data["AgentRun"].([]any); ok {
		for _, item := range data {
			r, ok := item.(map[string]any)
			if !ok {
				continue
			}
			run := AgentRun{
				DocID:         getString(r, "_docID"),
				AgentID:       getString(r, "agent_id"),
				AgentType:     getString(r, "agent_type"),
				BookID:        getString(r, "book_id"),
				JobID:         getString(r, "job_id"),
				Iterations:    getInt(r, "iterations"),
				Status:        getString(r, "status"),
				Success:       getBool(r, "success"),
				Error:         getString(r, "error"),
				MessagesJSON:  getString(r, "messages_json"),
				ToolCallsJSON: getString(r, "tool_calls_json"),
				ResultJSON:    getString(r, "result_json"),
			}
			if t, err := time.Parse(time.RFC3339, getString(r, "started_at")); err == nil {
				run.StartedAt = t
			}
			if t, err := time.Parse(time.RFC3339, getString(r, "completed_at")); err == nil {
				run.CompletedAt = t
			}
			runs = append(runs, run)
		}
	}

	return runs, nil
}

// GetAgentRun returns a specific agent run by ID.
func GetAgentRun(ctx context.Context, docID string) (*AgentRun, error) {
	client := svcctx.DefraClientFrom(ctx)
	if client == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		AgentRun(docID: "%s") {
			_docID
			agent_id
			agent_type
			book_id
			job_id
			started_at
			completed_at
			iterations
			status
			success
			error
			messages_json
			tool_calls_json
			result_json
		}
	}`, docID)

	resp, err := client.Query(ctx, query)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}

	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query error: %s", errMsg)
	}

	data, ok := resp.Data["AgentRun"].([]any)
	if !ok || len(data) == 0 {
		return nil, fmt.Errorf("agent run not found: %s", docID)
	}

	r, ok := data[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("invalid response format")
	}

	run := &AgentRun{
		DocID:         getString(r, "_docID"),
		AgentID:       getString(r, "agent_id"),
		AgentType:     getString(r, "agent_type"),
		BookID:        getString(r, "book_id"),
		JobID:         getString(r, "job_id"),
		Iterations:    getInt(r, "iterations"),
		Status:        getString(r, "status"),
		Success:       getBool(r, "success"),
		Error:         getString(r, "error"),
		MessagesJSON:  getString(r, "messages_json"),
		ToolCallsJSON: getString(r, "tool_calls_json"),
		ResultJSON:    getString(r, "result_json"),
	}
	if t, err := time.Parse(time.RFC3339, getString(r, "started_at")); err == nil {
		run.StartedAt = t
	}
	if t, err := time.Parse(time.RFC3339, getString(r, "completed_at")); err == nil {
		run.CompletedAt = t
	}

	return run, nil
}

func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getInt(m map[string]any, key string) int {
	if v, ok := m[key].(float64); ok {
		return int(v)
	}
	return 0
}

func getBool(m map[string]any, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}
