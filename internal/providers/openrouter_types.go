package providers

import "encoding/json"

// OpenRouter API request/response types

type openRouterRequest struct {
	Model          string                    `json:"model"`
	Messages       []openRouterMessage       `json:"messages"`
	Temperature    float64                   `json:"temperature,omitempty"`
	MaxTokens      int                       `json:"max_tokens,omitempty"`
	ResponseFormat *openRouterResponseFormat `json:"response_format,omitempty"`
	Tools          []Tool                    `json:"tools,omitempty"`
	Usage          *openRouterUsageRequest   `json:"usage,omitempty"` // Request cost tracking
}

type openRouterUsageRequest struct {
	Include bool `json:"include"`
}

type openRouterMessage struct {
	Role             string            `json:"role"`
	Content          any               `json:"content"`                     // string or []openRouterContent
	ToolCalls        []ToolCall        `json:"tool_calls,omitempty"`        // For assistant messages with tool calls
	ToolCallID       string            `json:"tool_call_id,omitempty"`      // For tool response messages
	ReasoningDetails []ReasoningDetail `json:"reasoning_details,omitempty"` // For reasoning models
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
			Role             string `json:"role"`
			Content          any    `json:"content"`
			ToolCalls        []struct {
				ID       string `json:"id"`
				Type     string `json:"type"`
				Function struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				} `json:"function"`
			} `json:"tool_calls,omitempty"`
			ReasoningDetails []ReasoningDetail `json:"reasoning_details,omitempty"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage struct {
		PromptTokens            int     `json:"prompt_tokens"`
		CompletionTokens        int     `json:"completion_tokens"`
		TotalTokens             int     `json:"total_tokens"`
		Cost                    float64 `json:"cost,omitempty"`                 // OpenRouter returns cost in USD
		NativeTotalCost         float64 `json:"native_total_cost,omitempty"`    // Alternative cost field
		CompletionTokensDetails struct {
			ReasoningTokens int `json:"reasoning_tokens"`
		} `json:"completion_tokens_details,omitempty"`
	} `json:"usage"`
	// Error is returned by OpenRouter when something goes wrong at the API/model level
	Error *openRouterError `json:"error,omitempty"`
}

type openRouterError struct {
	Message  string         `json:"message"`
	Code     any            `json:"code,omitempty"`     // Can be string or int
	Metadata map[string]any `json:"metadata,omitempty"` // Additional error context
}
