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
}

// OpenRouterClient implements LLMClient using the OpenRouter API.
type OpenRouterClient struct {
	apiKey       string
	baseURL      string
	defaultModel string
	client       *http.Client
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

	return &OpenRouterClient{
		apiKey:       cfg.APIKey,
		baseURL:      cfg.BaseURL,
		defaultModel: cfg.DefaultModel,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
	}
}

// Name returns the client identifier.
func (c *OpenRouterClient) Name() string {
	return OpenRouterName
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

	// Make request
	orResp, httpErr := c.doRequest(ctx, "/chat/completions", orReq)

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

// doRequest makes an HTTP request to OpenRouter.
func (c *OpenRouterClient) doRequest(ctx context.Context, path string, body any) (*openRouterResponse, error) {
	bodyBytes, err := json.Marshal(body)
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
		return nil, fmt.Errorf("request failed: %w", err)
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response: %w", err)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("OpenRouter error (status %d): %s", resp.StatusCode, string(respBody))
	}

	var orResp openRouterResponse
	if err := json.Unmarshal(respBody, &orResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return &orResp, nil
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
