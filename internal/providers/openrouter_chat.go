package providers

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
)

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

		// Include tool_calls for assistant messages (required by API)
		if len(m.ToolCalls) > 0 {
			orMsg.ToolCalls = m.ToolCalls
		}

		// Include tool_call_id for tool response messages
		if m.ToolCallID != "" {
			orMsg.ToolCallID = m.ToolCallID
		}

		// Include reasoning_details for reasoning models
		if len(m.ReasoningDetails) > 0 {
			orMsg.ReasoningDetails = m.ReasoningDetails
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
	result.ReasoningTokens = orResp.Usage.CompletionTokensDetails.ReasoningTokens
	result.ExecutionTime = time.Since(start)
	result.TotalTime = result.ExecutionTime

	// Include reasoning_details for reasoning models
	if len(orResp.Choices[0].Message.ReasoningDetails) > 0 {
		result.ReasoningDetails = orResp.Choices[0].Message.ReasoningDetails
	}

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
