package providers

import (
	"context"
	"encoding/json"
	"time"
)

// LLMClient is the primary interface for chat/completion requests.
// This matches the Python LLMClient pattern with call() and call_with_tools().
type LLMClient interface {
	// Chat sends a chat completion request.
	Chat(ctx context.Context, req *ChatRequest) (*ChatResult, error)

	// ChatWithTools sends a chat request with tool/function definitions.
	ChatWithTools(ctx context.Context, req *ChatRequest, tools []Tool) (*ChatResult, error)

	// Name returns the client identifier (e.g., "openrouter").
	Name() string
}

// OCRProvider handles image-to-text extraction.
// Separate from LLM because it has different rate limiting, retry patterns,
// and result handling (markdown text vs structured responses).
type OCRProvider interface {
	// Name returns the provider identifier (e.g., "mistral", "paddle").
	Name() string

	// ProcessImage extracts text from an image.
	ProcessImage(ctx context.Context, image []byte, pageNum int) (*OCRResult, error)

	// Rate limiting properties
	RequestsPerSecond() float64
	MaxRetries() int
	RetryDelayBase() time.Duration
}

// Message represents a chat message.
type Message struct {
	Role    string   `json:"role"` // "system", "user", "assistant"
	Content string   `json:"content"`
	Images  [][]byte `json:"-"` // For vision models (base64 encoded in request)
}

// ResponseFormat specifies structured output format.
type ResponseFormat struct {
	Type       string          `json:"type"` // "json_schema"
	JSONSchema json.RawMessage `json:"json_schema,omitempty"`
}

// ChatRequest is a request to an LLM.
type ChatRequest struct {
	// Required
	Messages []Message `json:"messages"`

	// Model selection (uses client default if empty)
	Model string `json:"model,omitempty"`

	// Generation parameters
	Temperature float64 `json:"temperature,omitempty"`
	MaxTokens   int     `json:"max_tokens,omitempty"`
	Timeout     time.Duration

	// Structured output
	ResponseFormat *ResponseFormat `json:"response_format,omitempty"`

	// Request tracking
	RequestID string `json:"-"`
}

// ChatResult is the complete response from an LLM call.
// Matches the Python LLMResult dataclass.
type ChatResult struct {
	// Response content
	Content    string          `json:"content"`
	ParsedJSON json.RawMessage `json:"parsed_json,omitempty"` // Parsed if ResponseFormat was set
	ToolCalls  []ToolCall      `json:"tool_calls,omitempty"`

	// Token counts
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	ReasoningTokens  int `json:"reasoning_tokens,omitempty"`
	TotalTokens      int `json:"total_tokens"`

	// Cost and timing
	CostUSD       float64       `json:"cost_usd"`
	QueueTime     time.Duration `json:"queue_time"`
	ExecutionTime time.Duration `json:"execution_time"`
	TotalTime     time.Duration `json:"total_time"`

	// Provider info
	Provider  string `json:"provider"`
	ModelUsed string `json:"model_used"`

	// Request tracking
	RequestID string `json:"request_id"`
	Attempts  int    `json:"attempts"`

	// Success/error
	Success      bool   `json:"success"`
	ErrorType    string `json:"error_type,omitempty"`
	ErrorMessage string `json:"error_message,omitempty"`
	RetryAfter   time.Duration
}

// Tool defines a function/tool that the LLM can call.
type Tool struct {
	Type     string       `json:"type"` // "function"
	Function ToolFunction `json:"function"`
}

// ToolFunction describes a callable function.
type ToolFunction struct {
	Name        string          `json:"name"`
	Description string          `json:"description,omitempty"`
	Parameters  json.RawMessage `json:"parameters,omitempty"` // JSON Schema
}

// ToolCall represents a tool invocation from the LLM.
type ToolCall struct {
	ID       string `json:"id"`
	Type     string `json:"type"` // "function"
	Function struct {
		Name      string `json:"name"`
		Arguments string `json:"arguments"` // JSON string
	} `json:"function"`
}

// OCRResult is the response from an OCR provider.
type OCRResult struct {
	// Success/content
	Success bool   `json:"success"`
	Text    string `json:"text"` // Markdown formatted

	// Metadata from provider (dimensions, detected images, etc.)
	Metadata map[string]any `json:"metadata,omitempty"`

	// Cost and timing
	CostUSD       float64       `json:"cost_usd"`
	ExecutionTime time.Duration `json:"execution_time"`

	// Error info
	ErrorMessage string `json:"error_message,omitempty"`
	RetryCount   int    `json:"retry_count"`
}
