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
		Usage:       &openRouterUsageRequest{Include: true}, // Request cost tracking
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

	// Set provider-adapted response format if specified.
	if req.ResponseFormat != nil {
		adaptedFormat, err := adaptedResponseFormat(model, req.ResponseFormat)
		if err != nil {
			return &ChatResult{
				RequestID:    requestID,
				Provider:     OpenRouterName,
				ModelUsed:    model,
				Success:      false,
				ErrorType:    "schema_adapter",
				ErrorMessage: err.Error(),
				TotalTime:    time.Since(start),
			}, fmt.Errorf("failed to adapt structured schema: %w", err)
		}
		orReq.ResponseFormat = adaptedFormat
	}

	// Add tools if specified
	if len(tools) > 0 {
		orReq.Tools = tools
	}

	result := &ChatResult{
		RequestID: requestID,
		Provider:  OpenRouterName,
		ModelUsed: model,
	}

	for attempt := 0; ; attempt++ {
		result.Attempts = attempt + 1

		// Make request (pass pointer for nonce injection on retries).
		orResp, httpErr := c.doRequest(ctx, "/chat/completions", &orReq)
		if httpErr != nil {
			result.Success = false
			result.ErrorType = "http_error"
			result.ErrorMessage = httpErr.Error()
			result.TotalTime = time.Since(start)
			result.ExecutionTime = result.TotalTime
			return result, httpErr
		}

		// Check for API-level error (can be returned with 200 status).
		if orResp.Error != nil {
			result.Success = false
			result.ErrorType = "api_error"
			result.ErrorMessage = orResp.Error.Message
			result.TotalTime = time.Since(start)
			result.ExecutionTime = result.TotalTime
			return result, fmt.Errorf("OpenRouter API error: %s", orResp.Error.Message)
		}

		// Parse response.
		if len(orResp.Choices) == 0 {
			result.Success = false
			result.ErrorType = "empty_response"
			result.ErrorMessage = fmt.Sprintf("no choices in response (model=%s, id=%s)", orResp.Model, orResp.ID)
			result.TotalTime = time.Since(start)
			result.ExecutionTime = result.TotalTime
			return result, fmt.Errorf("no choices in response (model=%s, id=%s)", orResp.Model, orResp.ID)
		}

		result.ModelUsed = orResp.Model
		result.PromptTokens += orResp.Usage.PromptTokens
		result.CompletionTokens += orResp.Usage.CompletionTokens
		result.TotalTokens += orResp.Usage.TotalTokens
		result.ReasoningTokens += orResp.Usage.CompletionTokensDetails.ReasoningTokens
		if orResp.Usage.NativeTotalCost > 0 {
			result.CostUSD += orResp.Usage.NativeTotalCost
		} else if orResp.Usage.Cost > 0 {
			result.CostUSD += orResp.Usage.Cost
		}

		choice := orResp.Choices[0]

		// Include reasoning_details for reasoning models.
		if len(choice.Message.ReasoningDetails) > 0 {
			result.ReasoningDetails = choice.Message.ReasoningDetails
		}

		// Extract tool calls if present.
		if len(choice.Message.ToolCalls) > 0 {
			result.ToolCalls = make([]ToolCall, len(choice.Message.ToolCalls))
			for i, tc := range choice.Message.ToolCalls {
				result.ToolCalls[i] = ToolCall{
					ID:   tc.ID,
					Type: tc.Type,
				}
				result.ToolCalls[i].Function.Name = tc.Function.Name
				result.ToolCalls[i].Function.Arguments = tc.Function.Arguments
			}
		}

		content := ""
		if choice.Message.Content != nil {
			switch contentValue := choice.Message.Content.(type) {
			case string:
				content = contentValue
			default:
				b, err := json.Marshal(contentValue)
				if err != nil {
					result.Success = false
					result.ErrorType = "content_marshal_error"
					result.ErrorMessage = fmt.Sprintf("failed to marshal content: %v", err)
					result.TotalTime = time.Since(start)
					result.ExecutionTime = result.TotalTime
					return result, fmt.Errorf("failed to marshal content: %w", err)
				}
				content = string(b)
			}
		}

		result.Content = content

		// Non-structured responses are complete at first successful provider reply.
		if req.ResponseFormat == nil {
			result.Success = true
			result.TotalTime = time.Since(start)
			result.ExecutionTime = result.TotalTime
			return result, nil
		}

		parsed, parseErr := parseStructuredJSON(content)
		var validationErr error
		if parseErr == nil {
			result.ParsedJSON = parsed
			validationErr = validateStructuredJSON(req.ResponseFormat.JSONSchema, parsed)
		}

		if parseErr == nil && validationErr == nil {
			result.Success = true
			result.ErrorType = ""
			result.ErrorMessage = ""
			result.TotalTime = time.Since(start)
			result.ExecutionTime = result.TotalTime
			return result, nil
		}

		issue := parseErr
		result.ErrorType = "json_parse"
		if issue == nil {
			issue = validationErr
			result.ErrorType = "schema_validation"
		}
		result.ErrorMessage = issue.Error()

		if attempt >= maxStructuredRepairAttempts {
			result.Success = false
			result.TotalTime = time.Since(start)
			result.ExecutionTime = result.TotalTime
			return result, nil
		}

		// Ask the model to repair the output using the same response schema.
		orReq.Messages = append(orReq.Messages,
			openRouterMessage{Role: "assistant", Content: content},
			openRouterMessage{
				Role:    "user",
				Content: structuredRepairPrompt(req.ResponseFormat.JSONSchema, content, issue),
			},
		)
	}
}
