package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/agent/observability"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Config configures an agent instance.
type Config struct {
	// ID uniquely identifies this agent (auto-generated if empty)
	ID string

	// Tools provides the agent's capabilities
	Tools Tools

	// InitialMessages sets up the conversation (system prompt + user prompt)
	InitialMessages []providers.Message

	// MaxIterations limits the agent loop (default: 15)
	MaxIterations int

	// Observability config (for debug tracing)
	AgentType string // e.g., "toc_finder", "toc_extract"
	BookID    string // Book being processed
	JobID     string // Job ID for correlation
	Debug     bool   // Enable debug logging to DefraDB
}

// Agent manages state for a single agent conversation.
// It generates WorkUnits and processes results, but doesn't execute anything itself.
// Jobs use Agents to coordinate multi-turn LLM interactions with tools.
type Agent struct {
	mu sync.Mutex

	// Configuration
	id            string
	tools         Tools
	maxIterations int

	// Conversation state
	messages []providers.Message

	// Iteration tracking
	iteration int
	startTime time.Time

	// Tool call state (within an iteration)
	pendingToolCalls []providers.ToolCall
	toolResults      map[string]string // tool_call_id -> result JSON

	// Completion state
	complete bool
	result   *Result

	// Observability (nil if debug disabled)
	logger *observability.Logger
}

// New creates a new Agent with the given configuration.
// Context is required for observability logging (creating initial "running" record).
func New(ctx context.Context, cfg Config) *Agent {
	id := cfg.ID
	if id == "" {
		id = uuid.New().String()
	}

	maxIterations := cfg.MaxIterations
	if maxIterations <= 0 {
		maxIterations = 15
	}

	// Copy initial messages
	messages := make([]providers.Message, len(cfg.InitialMessages))
	copy(messages, cfg.InitialMessages)

	// Create logger if debug enabled
	var logger *observability.Logger
	if cfg.Debug {
		logger = observability.NewLogger(ctx, id, cfg.AgentType, cfg.BookID, cfg.JobID)
	}

	return &Agent{
		id:            id,
		tools:         cfg.Tools,
		maxIterations: maxIterations,
		messages:      messages,
		toolResults:   make(map[string]string),
		startTime:     time.Now(),
		logger:        logger,
	}
}

// ID returns the agent's unique identifier.
func (a *Agent) ID() string {
	return a.id
}

// NextWorkUnits returns the next work unit(s) to execute.
// Returns nil when the agent is complete.
func (a *Agent) NextWorkUnits() []WorkUnit {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.complete {
		return nil
	}

	// If we have pending tool calls, return tool work units
	if len(a.pendingToolCalls) > 0 && len(a.toolResults) < len(a.pendingToolCalls) {
		var units []WorkUnit
		for _, tc := range a.pendingToolCalls {
			if _, done := a.toolResults[tc.ID]; !done {
				units = append(units, WorkUnit{
					Type:     WorkUnitTypeTool,
					AgentID:  a.id,
					ToolCall: &tc,
				})
			}
		}
		return units
	}

	// Otherwise, return an LLM work unit
	a.iteration++

	if a.iteration > a.maxIterations {
		a.complete = true
		a.result = &Result{
			Success:       false,
			Error:         fmt.Sprintf("agent did not complete within %d iterations", a.maxIterations),
			Iterations:    a.iteration - 1,
			MaxIterations: a.maxIterations,
			ExecutionTime: time.Since(a.startTime),
		}
		return nil
	}

	// Copy messages for the request to avoid mutating history
	// This is important because we attach images to the last message,
	// and we don't want those images to persist in the conversation history.
	requestMessages := make([]providers.Message, len(a.messages))
	for i, msg := range a.messages {
		// Copy the message (shallow copy is fine, we only modify Images)
		requestMessages[i] = msg
		// Clear any images from history to ensure only current image is sent
		requestMessages[i].Images = nil
	}

	req := &providers.ChatRequest{
		Messages: requestMessages,
	}

	// Add current images to the last message only
	// This ensures the LLM only sees the current page, not accumulated history
	if images := a.tools.GetImages(); len(images) > 0 {
		if len(req.Messages) > 0 {
			lastIdx := len(req.Messages) - 1
			req.Messages[lastIdx].Images = images
		}
	}

	return []WorkUnit{{
		Type:        WorkUnitTypeLLM,
		AgentID:     a.id,
		ChatRequest: req,
		Tools:       a.tools.GetTools(),
		Iteration:   a.iteration,
	}}
}

// HandleLLMResult processes the result of an LLM work unit.
func (a *Agent) HandleLLMResult(result *providers.ChatResult) {
	a.mu.Lock()
	defer a.mu.Unlock()

	// Build assistant message with all fields needed for API
	assistantMsg := providers.Message{
		Role:    "assistant",
		Content: result.Content,
	}

	// Include tool_calls in assistant message (required by API for multi-turn)
	if len(result.ToolCalls) > 0 {
		assistantMsg.ToolCalls = result.ToolCalls
	}

	// Include reasoning_details for reasoning models (encrypted thinking)
	if len(result.ReasoningDetails) > 0 {
		assistantMsg.ReasoningDetails = result.ReasoningDetails
	}

	// Check for tool calls
	if len(result.ToolCalls) > 0 {
		a.pendingToolCalls = result.ToolCalls
		a.toolResults = make(map[string]string) // Reset for new batch
		a.messages = append(a.messages, assistantMsg)
		return
	}

	// No tool calls - check if complete
	a.messages = append(a.messages, assistantMsg)

	if a.tools.IsComplete() {
		a.complete = true
		a.result = &Result{
			Success:       true,
			Iterations:    a.iteration,
			MaxIterations: a.maxIterations,
			ExecutionTime: time.Since(a.startTime),
			FinalMessages: a.messages,
			ToolResult:    a.tools.GetResult(),
		}
		return
	}

	// Not complete but no tool calls - prompt to continue
	a.messages = append(a.messages, providers.Message{
		Role:    "user",
		Content: "Please continue using the available tools to complete your task.",
	})
}

// HandleToolResult processes the result of a tool execution work unit.
func (a *Agent) HandleToolResult(toolCallID string, result string, err error) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if err != nil {
		errResult, _ := json.Marshal(map[string]string{
			"error": fmt.Sprintf("Tool execution failed: %v", err),
		})
		a.toolResults[toolCallID] = string(errResult)
	} else {
		a.toolResults[toolCallID] = result
	}

	// Check if all tool calls are done
	if len(a.toolResults) == len(a.pendingToolCalls) {
		// Add tool results to messages
		for _, tc := range a.pendingToolCalls {
			a.messages = append(a.messages, providers.Message{
				Role:       "tool",
				Content:    a.toolResults[tc.ID],
				ToolCallID: tc.ID,
			})
		}

		// Clear pending state
		a.pendingToolCalls = nil

		// Check if tools indicate completion
		if a.tools.IsComplete() {
			a.complete = true
			a.result = &Result{
				Success:       true,
				Iterations:    a.iteration,
				MaxIterations: a.maxIterations,
				ExecutionTime: time.Since(a.startTime),
				FinalMessages: a.messages,
				ToolResult:    a.tools.GetResult(),
			}
		}
	}
}

// ExecuteTool runs a tool synchronously. This is a convenience method
// for when tools don't need to be work units (e.g., fast local operations).
func (a *Agent) ExecuteTool(ctx context.Context, tc providers.ToolCall) (string, error) {
	args := make(map[string]any)
	if tc.Function.Arguments != "" {
		if err := json.Unmarshal([]byte(tc.Function.Arguments), &args); err != nil {
			return "", fmt.Errorf("failed to parse tool arguments: %w", err)
		}
	}

	result, err := a.tools.ExecuteTool(ctx, tc.Function.Name, args)

	// Log tool call if debug enabled
	if a.logger != nil {
		a.logger.LogToolCall(a.iteration, tc.Function.Name, args, result, err)
	}

	return result, err
}

// IsDone returns true if the agent has completed (success or failure).
func (a *Agent) IsDone() bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.complete
}

// Result returns the final result. Only valid after IsDone() returns true.
func (a *Agent) Result() *Result {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.result
}

// Iteration returns the current iteration number.
func (a *Agent) Iteration() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.iteration
}

// SaveLog persists the agent execution log to DefraDB.
// Should be called after IsDone() returns true.
// No-op if debug logging is disabled.
func (a *Agent) SaveLog(ctx context.Context) error {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.logger == nil {
		return nil
	}

	// Capture final messages
	a.logger.SetMessages(a.messages)

	// Determine success and error
	success := a.result != nil && a.result.Success
	var resultData any
	var err error
	if a.result != nil {
		resultData = a.result.ToolResult
		if !a.result.Success && a.result.Error != "" {
			err = fmt.Errorf("%s", a.result.Error)
		}
	}

	return a.logger.Save(ctx, success, a.iteration, resultData, err)
}

// HasLogger returns true if debug logging is enabled.
func (a *Agent) HasLogger() bool {
	return a.logger != nil
}

// UpdateProgress persists current iteration and tool calls to the database.
// Call this after each iteration to show real-time agent progress.
// No-op if debug logging is disabled.
func (a *Agent) UpdateProgress(ctx context.Context) {
	a.mu.Lock()
	defer a.mu.Unlock()

	if a.logger != nil {
		a.logger.UpdateProgress(ctx, a.iteration)
	}
}

// WorkUnit represents a unit of work the agent needs executed.
type WorkUnit struct {
	Type        WorkUnitType
	AgentID     string
	ChatRequest *providers.ChatRequest
	Tools       []providers.Tool // For LLM calls
	ToolCall    *providers.ToolCall
	Iteration   int
}

// WorkUnitType distinguishes LLM calls from tool executions.
type WorkUnitType string

const (
	WorkUnitTypeLLM  WorkUnitType = "llm"
	WorkUnitTypeTool WorkUnitType = "tool"
)
