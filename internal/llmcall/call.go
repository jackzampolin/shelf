// Package llmcall provides LLM call recording and querying for traceability.
// Every LLM API call is recorded with its prompt key, response, and metrics.
package llmcall

import (
	"encoding/json"
	"log/slog"
	"time"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/providers"
)

// Call represents a recorded LLM API call.
type Call struct {
	// Unique identifier
	ID string `json:"id"`

	// Timing
	Timestamp time.Time `json:"timestamp"`
	LatencyMs int       `json:"latency_ms"`

	// Context references
	BookID string `json:"book_id,omitempty"`
	PageID string `json:"page_id,omitempty"`
	JobID  string `json:"job_id,omitempty"`

	// Prompt traceability
	PromptKey string `json:"prompt_key"`
	PromptCID string `json:"prompt_cid,omitempty"` // Content-addressed ID linking to the exact prompt version used

	// Model info
	Provider    string   `json:"provider"`
	Model       string   `json:"model"`
	Temperature *float64 `json:"temperature,omitempty"`

	// Token usage
	InputTokens  int `json:"input_tokens"`
	OutputTokens int `json:"output_tokens"`

	// Response
	Response  string          `json:"response"`
	ToolCalls json.RawMessage `json:"tool_calls,omitempty"`

	// Status
	Success bool   `json:"success"`
	Error   string `json:"error,omitempty"`
}

// RecordOptions provides context for recording an LLM call.
type RecordOptions struct {
	// Context references (all optional)
	BookID string
	PageID string
	JobID  string

	// Prompt identification (required for traceability)
	PromptKey string
	PromptCID string // Content-addressed ID linking to exact prompt version

	// Request parameters (pointer to distinguish "not set" from "set to 0")
	Temperature *float64

	// Optional logger for non-fatal serialization warnings.
	Logger *slog.Logger
}

// FromChatResult creates a Call from a ChatResult.
// Returns nil if result is nil.
func FromChatResult(result *providers.ChatResult, opts RecordOptions) *Call {
	if result == nil {
		return nil
	}

	call := &Call{
		ID:           uuid.New().String(),
		Timestamp:    time.Now(),
		LatencyMs:    int(result.ExecutionTime.Milliseconds()),
		BookID:       opts.BookID,
		PageID:       opts.PageID,
		JobID:        opts.JobID,
		PromptKey:    opts.PromptKey,
		PromptCID:    opts.PromptCID,
		Provider:     result.Provider,
		Model:        result.ModelUsed,
		InputTokens:  result.PromptTokens,
		OutputTokens: result.CompletionTokens,
		Response:     result.Content,
		Success:      result.Success,
	}

	if opts.Temperature != nil {
		call.Temperature = opts.Temperature
	}

	if !result.Success {
		call.Error = result.ErrorMessage
	}

	// Serialize tool calls if present
	if len(result.ToolCalls) > 0 {
		if data, err := json.Marshal(result.ToolCalls); err != nil {
			logger := opts.Logger
			if logger == nil {
				logger = slog.Default()
			}
			logger.Warn("failed to serialize tool calls for LLM call record",
				"error", err,
				"tool_call_count", len(result.ToolCalls))
		} else {
			call.ToolCalls = data
		}
	}

	return call
}

// ToMap converts the Call to a map for DefraDB insertion.
func (c *Call) ToMap() map[string]any {
	m := map[string]any{
		"id":            c.ID,
		"timestamp":     c.Timestamp,
		"latency_ms":    c.LatencyMs,
		"prompt_key":    c.PromptKey,
		"provider":      c.Provider,
		"model":         c.Model,
		"input_tokens":  c.InputTokens,
		"output_tokens": c.OutputTokens,
		"response":      c.Response,
		"success":       c.Success,
	}

	if c.BookID != "" {
		m["book_id"] = c.BookID
	}
	if c.PageID != "" {
		m["page_id"] = c.PageID
	}
	if c.JobID != "" {
		m["job_id"] = c.JobID
	}
	if c.PromptCID != "" {
		m["prompt_cid"] = c.PromptCID
	}
	if c.Temperature != nil {
		m["temperature"] = *c.Temperature
	}
	if c.Error != "" {
		m["error"] = c.Error
	}
	if len(c.ToolCalls) > 0 {
		// Convert to string so GraphQL sees it as a JSON string literal,
		// not raw JSON syntax that the parser would try to interpret
		m["tool_calls"] = string(c.ToolCalls)
	}

	return m
}
