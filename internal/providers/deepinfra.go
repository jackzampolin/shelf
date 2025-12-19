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
)

const (
	DeepInfraOCRName    = "deepinfra"
	DeepInfraBaseURL    = "https://api.deepinfra.com/v1/openai"
	DeepInfraDefaultOCRPrompt = "Extract all text from this image. Preserve the structure and formatting as much as possible. Output only the extracted text."
)

// DeepInfraOCRConfig holds configuration for the DeepInfra OCR client.
type DeepInfraOCRConfig struct {
	APIKey       string
	BaseURL      string
	Model        string        // e.g., "Qwen/Qwen2-VL-72B-Instruct", "ds-paddleocr-vl"
	Prompt       string        // Custom OCR prompt
	Temperature  float64
	MaxTokens    int
	Timeout      time.Duration
	RateLimit    float64       // Requests per second
}

// DeepInfraOCRClient implements OCRProvider using DeepInfra's OpenAI-compatible API.
type DeepInfraOCRClient struct {
	apiKey      string
	baseURL     string
	model       string
	prompt      string
	temperature float64
	maxTokens   int
	rateLimit   float64
	client      *http.Client
}

// NewDeepInfraOCRClient creates a new DeepInfra OCR client.
func NewDeepInfraOCRClient(cfg DeepInfraOCRConfig) *DeepInfraOCRClient {
	if cfg.BaseURL == "" {
		cfg.BaseURL = DeepInfraBaseURL
	}
	if cfg.Model == "" {
		cfg.Model = "PaddlePaddle/PaddleOCR-VL-0.9B" // Default PaddleOCR model
	}
	if cfg.Prompt == "" {
		cfg.Prompt = DeepInfraDefaultOCRPrompt
	}
	if cfg.Temperature == 0 {
		cfg.Temperature = 0.1
	}
	if cfg.MaxTokens == 0 {
		cfg.MaxTokens = 8000
	}
	if cfg.Timeout == 0 {
		cfg.Timeout = 120 * time.Second
	}
	if cfg.RateLimit == 0 {
		cfg.RateLimit = 150.0 // Default 150 RPS
	}

	return &DeepInfraOCRClient{
		apiKey:      cfg.APIKey,
		baseURL:     cfg.BaseURL,
		model:       cfg.Model,
		prompt:      cfg.Prompt,
		temperature: cfg.Temperature,
		maxTokens:   cfg.MaxTokens,
		rateLimit:   cfg.RateLimit,
		client: &http.Client{
			Timeout: cfg.Timeout,
		},
	}
}

// Name returns the provider identifier.
func (c *DeepInfraOCRClient) Name() string {
	return DeepInfraOCRName
}

// RequestsPerSecond returns the rate limit.
func (c *DeepInfraOCRClient) RequestsPerSecond() float64 {
	return c.rateLimit
}

// MaxRetries returns the maximum retry attempts.
func (c *DeepInfraOCRClient) MaxRetries() int {
	return 3
}

// RetryDelayBase returns the base delay for exponential backoff.
func (c *DeepInfraOCRClient) RetryDelayBase() time.Duration {
	return 2 * time.Second
}

// HealthCheck verifies the DeepInfra API is reachable and the API key is valid.
// Uses the /models endpoint to check connectivity without consuming tokens.
func (c *DeepInfraOCRClient) HealthCheck(ctx context.Context) error {
	// DeepInfra uses OpenAI-compatible API, check /models endpoint
	req, err := http.NewRequestWithContext(ctx, "GET", c.baseURL+"/models", nil)
	if err != nil {
		return fmt.Errorf("failed to create health check request: %w", err)
	}

	req.Header.Set("Authorization", "Bearer "+c.apiKey)

	resp, err := c.client.Do(req)
	if err != nil {
		return fmt.Errorf("health check request failed: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode == http.StatusUnauthorized {
		return fmt.Errorf("invalid API key")
	}
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("health check failed with status %d", resp.StatusCode)
	}

	return nil
}

// ProcessImage extracts text from an image using DeepInfra vision model.
func (c *DeepInfraOCRClient) ProcessImage(ctx context.Context, image []byte, pageNum int) (*OCRResult, error) {
	start := time.Now()

	// Encode image to base64
	imageBase64 := base64.StdEncoding.EncodeToString(image)

	// Build chat completion request with vision
	reqBody := deepInfraRequest{
		Model: c.model,
		Messages: []deepInfraMessage{
			{
				Role: "user",
				Content: []deepInfraContent{
					{Type: "text", Text: c.prompt},
					{
						Type: "image_url",
						ImageURL: &deepInfraImageURL{
							URL: "data:image/png;base64," + imageBase64,
						},
					},
				},
			},
		},
		Temperature: c.temperature,
		MaxTokens:   c.maxTokens,
	}

	// Make request
	resp, err := c.doRequest(ctx, "/chat/completions", reqBody)
	if err != nil {
		return &OCRResult{
			Success:       false,
			ErrorMessage:  err.Error(),
			ExecutionTime: time.Since(start),
		}, err
	}

	// Check for choices
	if len(resp.Choices) == 0 {
		return &OCRResult{
			Success:       false,
			ErrorMessage:  "no response choices from model",
			ExecutionTime: time.Since(start),
		}, fmt.Errorf("no response choices from model")
	}

	text := resp.Choices[0].Message.Content

	// Build metadata
	metadata := map[string]any{
		"model_used":        resp.Model,
		"prompt_tokens":     resp.Usage.PromptTokens,
		"completion_tokens": resp.Usage.CompletionTokens,
		"total_tokens":      resp.Usage.TotalTokens,
	}

	// Extract cost if available
	cost := 0.0
	if resp.Usage.EstimatedCost > 0 {
		cost = resp.Usage.EstimatedCost
	}

	return &OCRResult{
		Success:       true,
		Text:          text,
		Metadata:      metadata,
		CostUSD:       cost,
		ExecutionTime: time.Since(start),
	}, nil
}

// doRequest makes an HTTP request to DeepInfra API.
func (c *DeepInfraOCRClient) doRequest(ctx context.Context, path string, body any) (*deepInfraResponse, error) {
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
		var errResp deepInfraErrorResponse
		if json.Unmarshal(respBody, &errResp) == nil && errResp.Error.Message != "" {
			return nil, fmt.Errorf("DeepInfra error (status %d): %s", resp.StatusCode, errResp.Error.Message)
		}
		return nil, fmt.Errorf("DeepInfra error (status %d): %s", resp.StatusCode, string(respBody))
	}

	var diResp deepInfraResponse
	if err := json.Unmarshal(respBody, &diResp); err != nil {
		return nil, fmt.Errorf("failed to unmarshal response: %w", err)
	}

	return &diResp, nil
}

// DeepInfra API types (OpenAI-compatible)

type deepInfraRequest struct {
	Model       string             `json:"model"`
	Messages    []deepInfraMessage `json:"messages"`
	Temperature float64            `json:"temperature,omitempty"`
	MaxTokens   int                `json:"max_tokens,omitempty"`
	TopP        float64            `json:"top_p,omitempty"`
}

type deepInfraMessage struct {
	Role    string            `json:"role"`
	Content any               `json:"content"` // string or []deepInfraContent
}

type deepInfraContent struct {
	Type     string            `json:"type"`
	Text     string            `json:"text,omitempty"`
	ImageURL *deepInfraImageURL `json:"image_url,omitempty"`
}

type deepInfraImageURL struct {
	URL    string `json:"url"`
	Detail string `json:"detail,omitempty"`
}

type deepInfraResponse struct {
	ID      string `json:"id"`
	Model   string `json:"model"`
	Choices []struct {
		Index   int `json:"index"`
		Message struct {
			Role    string `json:"role"`
			Content string `json:"content"`
		} `json:"message"`
		FinishReason string `json:"finish_reason"`
	} `json:"choices"`
	Usage struct {
		PromptTokens     int     `json:"prompt_tokens"`
		CompletionTokens int     `json:"completion_tokens"`
		TotalTokens      int     `json:"total_tokens"`
		EstimatedCost    float64 `json:"estimated_cost,omitempty"`
	} `json:"usage"`
}

type deepInfraErrorResponse struct {
	Error struct {
		Message string `json:"message"`
		Type    string `json:"type"`
	} `json:"error"`
}

// Verify interface
var _ OCRProvider = (*DeepInfraOCRClient)(nil)
