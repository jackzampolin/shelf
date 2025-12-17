package providers

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"

	"github.com/google/uuid"
)

const (
	OpenRouterName    = "openrouter"
	OpenRouterBaseURL = "https://openrouter.ai/api/v1"
)

// OpenRouterConfig holds configuration for the OpenRouter client.
type OpenRouterConfig struct {
	APIKey       string
	BaseURL      string
	DefaultModel string
	Timeout      time.Duration
	// Rate limiting
	RPS        float64       // Requests per second (default: 150)
	MaxRetries int           // Max retry attempts (default: 3)
	RetryDelay time.Duration // Base delay between retries (default: 1s)
}

// OpenRouterClient implements LLMClient using the OpenRouter API.
type OpenRouterClient struct {
	apiKey       string
	baseURL      string
	defaultModel string
	client       *http.Client
	// Rate limiting
	rps        float64
	maxRetries int
	retryDelay time.Duration
}

// NewOpenRouterClient creates a new OpenRouter client.
func NewOpenRouterClient(cfg OpenRouterConfig) *OpenRouterClient {
	if cfg.BaseURL == "" {
		cfg.BaseURL = OpenRouterBaseURL
	}
	if cfg.DefaultModel == "" {
		cfg.DefaultModel = "anthropic/claude-3.5-sonnet"
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 120 * time.Second
	}
	if cfg.RPS == 0 {
		cfg.RPS = 150.0 // Default 150 RPS
	}
	if cfg.MaxRetries == 0 {
		cfg.MaxRetries = 3
	}
	if cfg.RetryDelay == 0 {
		cfg.RetryDelay = time.Second
	}

	return &OpenRouterClient{
		apiKey:       cfg.APIKey,
		baseURL:      cfg.BaseURL,
		defaultModel: cfg.DefaultModel,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
		rps:        cfg.RPS,
		maxRetries: cfg.MaxRetries,
		retryDelay: cfg.RetryDelay,
	}
}

// Name returns the client identifier.
func (c *OpenRouterClient) Name() string {
	return OpenRouterName
}

// RequestsPerSecond returns the RPS limit for rate limiting.
func (c *OpenRouterClient) RequestsPerSecond() float64 {
	return c.rps
}

// MaxRetries returns the maximum retry attempts.
func (c *OpenRouterClient) MaxRetries() int {
	return c.maxRetries
}

// RetryDelayBase returns the base delay between retries.
func (c *OpenRouterClient) RetryDelayBase() time.Duration {
	return c.retryDelay
}

// Chat sends a chat completion request.
func (c *OpenRouterClient) Chat(ctx context.Context, req *ChatRequest) (*ChatResult, error) {
	return c.doChat(ctx, req, nil)
}

// ChatWithTools sends a chat request with tool definitions.
func (c *OpenRouterClient) ChatWithTools(ctx context.Context, req *ChatRequest, tools []Tool) (*ChatResult, error) {
	return c.doChat(ctx, req, tools)
}

func (c *OpenRouterClient) doChat(ctx context.Context, req *ChatRequest, tools []Tool) (*ChatResult, error) {
	start := time.Now()

	// Generate request ID if not provided
	requestID := req.RequestID
	if requestID == "" {
		requestID = uuid.New().String()
	}

	model := req.Model
	if model == "" {
		model = c.defaultModel
	}

	// Build OpenRouter request
	orReq := openRouterRequest{
		Model:       model,
		Messages:    make([]openRouterMessage, 0, len(req.Messages)),
		Temperature: req.Temperature,
		MaxTokens:   req.MaxTokens,
	}

	// Convert messages
	for _, m := range req.Messages {
		orMsg := openRouterMessage{
			Role: m.Role,
		}

		// Handle vision messages with images
		if len(m.Images) > 0 {
			content := []openRouterContent{
				{Type: "text", Text: m.Content},
			}
			for _, img := range m.Images {
				content = append(content, openRouterContent{
					Type: "image_url",
					ImageURL: &openRouterImageURL{
						URL: "data:image/jpeg;base64," + base64.StdEncoding.EncodeToString(img),
					},
				})
			}
			orMsg.Content = content
		} else {
			orMsg.Content = m.Content
		}

		orReq.Messages = append(orReq.Messages, orMsg)
	}

	// Set response format if specified
	if req.ResponseFormat != nil {
		orReq.ResponseFormat = &openRouterResponseFormat{
			Type:       req.ResponseFormat.Type,
			JSONSchema: req.ResponseFormat.JSONSchema,
		}
	}

	// Add tools if specified
	if len(tools) > 0 {
		orReq.Tools = tools
	}

	// Make request (pass pointer for nonce injection on retries)
	orResp, httpErr := c.doRequest(ctx, "/chat/completions", &orReq)

	result := &ChatResult{
		RequestID: requestID,
		Provider:  OpenRouterName,
		Attempts:  1,
	}

	if httpErr != nil {
		result.Success = false
		result.ErrorType = "http_error"
		result.ErrorMessage = httpErr.Error()
		result.TotalTime = time.Since(start)
		return result, httpErr
	}

	// Parse response
	if len(orResp.Choices) == 0 {
		result.Success = false
		result.ErrorType = "empty_response"
		result.ErrorMessage = "no choices in response"
		result.TotalTime = time.Since(start)
		return result, fmt.Errorf("no choices in response")
	}

	// Extract content
	content := ""
	if orResp.Choices[0].Message.Content != nil {
		switch c := orResp.Choices[0].Message.Content.(type) {
		case string:
			content = c
		default:
			b, err := json.Marshal(c)
			if err != nil {
				result.Success = false
				result.ErrorType = "content_marshal_error"
				result.ErrorMessage = fmt.Sprintf("failed to marshal content: %v", err)
				result.TotalTime = time.Since(start)
				return result, fmt.Errorf("failed to marshal content: %w", err)
			}
			content = string(b)
		}
	}

	result.Success = true
	result.Content = content
	result.ModelUsed = orResp.Model
	result.PromptTokens = orResp.Usage.PromptTokens
	result.CompletionTokens = orResp.Usage.CompletionTokens
	result.TotalTokens = orResp.Usage.TotalTokens
	result.ExecutionTime = time.Since(start)
	result.TotalTime = result.ExecutionTime

	// Parse JSON if structured output was requested
	if req.ResponseFormat != nil && content != "" {
		var parsed json.RawMessage
		if err := json.Unmarshal([]byte(content), &parsed); err == nil {
			result.ParsedJSON = parsed
		} else {
			result.Success = false
			result.ErrorType = "json_parse"
			result.ErrorMessage = fmt.Sprintf("failed to parse JSON response: %v", err)
		}
	}

	// Extract tool calls if present
	if len(orResp.Choices[0].Message.ToolCalls) > 0 {
		result.ToolCalls = make([]ToolCall, len(orResp.Choices[0].Message.ToolCalls))
		for i, tc := range orResp.Choices[0].Message.ToolCalls {
			result.ToolCalls[i] = ToolCall{
				ID:   tc.ID,
				Type: tc.Type,
			}
			result.ToolCalls[i].Function.Name = tc.Function.Name
			result.ToolCalls[i].Function.Arguments = tc.Function.Arguments
		}
	}

	return result, nil
}

// doRequest makes an HTTP request to OpenRouter with retry logic.
func (c *OpenRouterClient) doRequest(ctx context.Context, path string, body any) (*openRouterResponse, error) {
	// Cast to openRouterRequest for nonce injection
	orReq, ok := body.(*openRouterRequest)
	if !ok {
		return nil, fmt.Errorf("body must be *openRouterRequest")
	}

	var lastErr error
	for attempt := 0; attempt < c.maxRetries; attempt++ {
		// Check context before each attempt
		if err := ctx.Err(); err != nil {
			return nil, err
		}

		// Inject nonce for retries on 413/422 (makes request "different")
		if attempt > 0 && lastErr != nil {
			c.injectNonce(orReq, attempt)
		}

		bodyBytes, err := json.Marshal(orReq)
		if err != nil {
			return nil, fmt.Errorf("failed to marshal request: %w", err)
		}

		req, err := http.NewRequestWithContext(ctx, "POST", c.baseURL+path, bytes.NewReader(bodyBytes))
		if err != nil {
			return nil, fmt.Errorf("failed to create request: %w", err)
		}

		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
		req.Header.Set("HTTP-Referer", "https://github.com/jackzampolin/shelf")
		req.Header.Set("X-Title", "Shelf")

		resp, err := c.client.Do(req)
		if err != nil {
			// Network error - retry
			lastErr = fmt.Errorf("request failed: %w", err)
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		respBody, err := io.ReadAll(resp.Body)
		resp.Body.Close()
		if err != nil {
			lastErr = fmt.Errorf("failed to read response: %w", err)
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		// Check if we should retry based on status code
		if c.shouldRetry(resp.StatusCode) {
			lastErr = fmt.Errorf("OpenRouter error (status %d): %s", resp.StatusCode, string(respBody))
			c.sleepWithJitter(ctx, attempt)
			continue
		}

		// Non-retryable error
		if resp.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("OpenRouter error (status %d): %s", resp.StatusCode, string(respBody))
		}

		var orResp openRouterResponse
		if err := json.Unmarshal(respBody, &orResp); err != nil {
			return nil, fmt.Errorf("failed to unmarshal response: %w", err)
		}

		return &orResp, nil
	}

	return nil, fmt.Errorf("max retries (%d) exceeded: %w", c.maxRetries, lastErr)
}

// shouldRetry returns true for status codes that should be retried.
func (c *OpenRouterClient) shouldRetry(statusCode int) bool {
	switch statusCode {
	case 413: // Payload Too Large - retry with nonce
		return true
	case 422: // Unprocessable Entity - retry with nonce (often cache/format issues)
		return true
	case 429: // Rate Limited
		return true
	default:
		// Retry on server errors (500+)
		return statusCode >= 500
	}
}

// injectNonce adds a unique comment to the last user message to make the request different.
// This helps bypass caching issues that can cause 413/422 errors.
func (c *OpenRouterClient) injectNonce(req *openRouterRequest, attempt int) {
	if len(req.Messages) == 0 {
		return
	}

	// Find the last user message
	for i := len(req.Messages) - 1; i >= 0; i-- {
		if req.Messages[i].Role == "user" {
			nonce := uuid.New().String()[:16]
			comment := fmt.Sprintf("\n<!-- retry_%d_id: %s -->", attempt, nonce)

			// Handle both string and array content
			switch content := req.Messages[i].Content.(type) {
			case string:
				req.Messages[i].Content = content + comment
			case []any:
				// For multipart content, find text part and append
				for j, part := range content {
					if partMap, ok := part.(map[string]any); ok {
						if partMap["type"] == "text" {
							if text, ok := partMap["text"].(string); ok {
								partMap["text"] = text + comment
								content[j] = partMap
								break
							}
						}
					}
				}
				req.Messages[i].Content = content
			}
			break
		}
	}
}

// sleepWithJitter sleeps for a duration with jitter, respecting context cancellation.
func (c *OpenRouterClient) sleepWithJitter(ctx context.Context, attempt int) {
	// Base delay with exponential backoff: 0.5s, 1s, 2s, ...
	baseDelay := c.retryDelay * time.Duration(1<<attempt)
	if baseDelay > 10*time.Second {
		baseDelay = 10 * time.Second
	}

	// Add jitter: -20% to +30%
	jitter := time.Duration(float64(baseDelay) * (0.8 + 0.5*float64(time.Now().UnixNano()%1000)/1000))

	select {
	case <-ctx.Done():
	case <-time.After(jitter):
	}
}

// OpenRouter API types

type openRouterRequest struct {
	Model          string                    `json:"model"`
	Messages       []openRouterMessage       `json:"messages"`
	Temperature    float64                   `json:"temperature,omitempty"`
	MaxTokens      int                       `json:"max_tokens,omitempty"`
	ResponseFormat *openRouterResponseFormat `json:"response_format,omitempty"`
	Tools          []Tool                    `json:"tools,omitempty"`
}

type openRouterMessage struct {
	Role    string `json:"role"`
	Content any    `json:"content"` // string or []openRouterContent
}

type openRouterContent struct {
	Type     string              `json:"type"`
	Text     string              `json:"text,omitempty"`
	ImageURL *openRouterImageURL `json:"image_url,omitempty"`
}

type openRouterImageURL struct {
	URL string `json:"url"`
}

type openRouterResponseFormat struct {
	Type       string          `json:"type"`
	JSONSchema json.RawMessage `json:"json_schema,omitempty"`
}

type openRouterResponse struct {
	ID      string `json:"id"`
	Model   string `json:"model"`
	Choices []struct {
		Message struct {
			Role      string `json:"role"`
			Content   any    `json:"content"`
			ToolCalls []struct {
				ID       string `json:"id"`
				Type     string `json:"type"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls,omitempty"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage struct {
		PromptTokens     int `json:"prompt_tokens"`
		CompletionTokens int `json:"completion_tokens"`
		TotalTokens      int `json:"total_tokens"`
	} `json:"usage"`
}

// Verify interface
var _ LLMClient = (*OpenRouterClient)(nil)
