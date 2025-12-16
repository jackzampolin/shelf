package providers

import (
	"context"
	"encoding/json"
	"fmt"
	"sync/atomic"
	"time"
)

const MockClientName = "mock"

// MockClient is an LLMClient for testing.
type MockClient struct {
	// Configurable behavior
	Latency      time.Duration
	ShouldFail   bool
	FailAfter    int // Fail after N requests (0 = never)
	ResponseText string
	ResponseJSON json.RawMessage

	// Rate limiting
	RPM        int
	Retries    int
	RetryDelay time.Duration

	// State
	requestCount atomic.Int64
}

// NewMockClient creates a new mock client with sensible defaults.
func NewMockClient() *MockClient {
	return &MockClient{
		Latency:      10 * time.Millisecond,
		ResponseText: "mock response",
		RPM:          60,
		Retries:      3,
		RetryDelay:   time.Second,
	}
}

// Name returns the client identifier.
func (c *MockClient) Name() string {
	return MockClientName
}

// RequestsPerMinute returns the RPM limit for rate limiting.
func (c *MockClient) RequestsPerMinute() int {
	return c.RPM
}

// MaxRetries returns the maximum retry attempts.
func (c *MockClient) MaxRetries() int {
	return c.Retries
}

// RetryDelayBase returns the base delay between retries.
func (c *MockClient) RetryDelayBase() time.Duration {
	return c.RetryDelay
}

// Chat sends a mock chat request.
func (c *MockClient) Chat(ctx context.Context, req *ChatRequest) (*ChatResult, error) {
	return c.doRequest(ctx, req, nil)
}

// ChatWithTools sends a mock chat request with tools.
func (c *MockClient) ChatWithTools(ctx context.Context, req *ChatRequest, tools []Tool) (*ChatResult, error) {
	return c.doRequest(ctx, req, tools)
}

func (c *MockClient) doRequest(ctx context.Context, req *ChatRequest, tools []Tool) (*ChatResult, error) {
	start := time.Now()
	count := c.requestCount.Add(1)

	result := &ChatResult{
		RequestID: fmt.Sprintf("mock-%d", count),
		Provider:  MockClientName,
		ModelUsed: req.Model,
		Attempts:  1,
	}

	// Check if we should fail
	if c.ShouldFail {
		result.Success = false
		result.ErrorType = "mock_failure"
		result.ErrorMessage = "mock client configured to fail"
		result.TotalTime = time.Since(start)
		return result, fmt.Errorf("mock client configured to fail")
	}
	if c.FailAfter > 0 && int(count) > c.FailAfter {
		result.Success = false
		result.ErrorType = "mock_failure"
		result.ErrorMessage = fmt.Sprintf("mock client failed after %d requests", c.FailAfter)
		result.TotalTime = time.Since(start)
		return result, fmt.Errorf("mock client failed after %d requests", c.FailAfter)
	}

	// Simulate latency
	select {
	case <-time.After(c.Latency):
	case <-ctx.Done():
		result.Success = false
		result.ErrorType = "context_cancelled"
		result.ErrorMessage = ctx.Err().Error()
		result.TotalTime = time.Since(start)
		return result, ctx.Err()
	}

	// Build response
	result.Success = true
	result.Content = c.ResponseText
	result.ExecutionTime = time.Since(start)
	result.TotalTime = result.ExecutionTime

	// Simulate token counting
	promptTokens := 0
	for _, m := range req.Messages {
		promptTokens += len(m.Content) / 4 // Rough estimate
	}
	completionTokens := len(c.ResponseText) / 4

	result.PromptTokens = promptTokens
	result.CompletionTokens = completionTokens
	result.TotalTokens = promptTokens + completionTokens
	result.CostUSD = 0.001 // Mock cost

	// Handle structured output
	if req.ResponseFormat != nil && len(c.ResponseJSON) > 0 {
		result.ParsedJSON = c.ResponseJSON
		result.Content = string(c.ResponseJSON)
	}

	// Mock tool calls if tools were provided
	if len(tools) > 0 {
		result.ToolCalls = []ToolCall{
			{
				ID:   "mock-tool-call-1",
				Type: "function",
				Function: struct {
					Name      string `json:"name"`
					Arguments string `json:"arguments"`
				}{
					Name:      tools[0].Function.Name,
					Arguments: `{}`,
				},
			},
		}
	}

	return result, nil
}

// RequestCount returns the number of requests made.
func (c *MockClient) RequestCount() int64 {
	return c.requestCount.Load()
}

// Reset resets the request counter.
func (c *MockClient) Reset() {
	c.requestCount.Store(0)
}

// Verify interface
var _ LLMClient = (*MockClient)(nil)

// MockOCRProvider is an OCRProvider for testing.
type MockOCRProvider struct {
	ProviderName string
	Latency      time.Duration
	ShouldFail   bool
	FailAfter    int
	ResponseText string
	RPS          float64
	Retries      int
	RetryDelay   time.Duration

	requestCount atomic.Int64
}

// NewMockOCRProvider creates a new mock OCR provider.
func NewMockOCRProvider() *MockOCRProvider {
	return &MockOCRProvider{
		ProviderName: "mock-ocr",
		Latency:      10 * time.Millisecond,
		ResponseText: "mock OCR text",
		RPS:          10.0,
		Retries:      3,
		RetryDelay:   time.Second,
	}
}

// Name returns the provider identifier.
func (p *MockOCRProvider) Name() string {
	return p.ProviderName
}

// RequestsPerSecond returns the rate limit.
func (p *MockOCRProvider) RequestsPerSecond() float64 {
	return p.RPS
}

// MaxRetries returns the max retry count.
func (p *MockOCRProvider) MaxRetries() int {
	return p.Retries
}

// RetryDelayBase returns the base retry delay.
func (p *MockOCRProvider) RetryDelayBase() time.Duration {
	return p.RetryDelay
}

// ProcessImage extracts text from an image.
func (p *MockOCRProvider) ProcessImage(ctx context.Context, image []byte, pageNum int) (*OCRResult, error) {
	start := time.Now()
	count := p.requestCount.Add(1)

	result := &OCRResult{}

	// Check if we should fail
	if p.ShouldFail {
		result.Success = false
		result.ErrorMessage = "mock OCR provider configured to fail"
		result.ExecutionTime = time.Since(start)
		return result, fmt.Errorf("mock OCR provider configured to fail")
	}
	if p.FailAfter > 0 && int(count) > p.FailAfter {
		result.Success = false
		result.ErrorMessage = fmt.Sprintf("mock OCR provider failed after %d requests", p.FailAfter)
		result.ExecutionTime = time.Since(start)
		return result, fmt.Errorf("mock OCR provider failed after %d requests", p.FailAfter)
	}

	// Simulate latency
	select {
	case <-time.After(p.Latency):
	case <-ctx.Done():
		result.Success = false
		result.ErrorMessage = ctx.Err().Error()
		result.ExecutionTime = time.Since(start)
		return result, ctx.Err()
	}

	result.Success = true
	result.Text = fmt.Sprintf("Page %d: %s", pageNum, p.ResponseText)
	result.ExecutionTime = time.Since(start)
	result.CostUSD = 0.001
	result.Metadata = map[string]any{
		"page_num":    pageNum,
		"char_count":  len(result.Text),
		"provider":    p.ProviderName,
		"image_bytes": len(image),
	}

	return result, nil
}

// RequestCount returns the number of requests made.
func (p *MockOCRProvider) RequestCount() int64 {
	return p.requestCount.Load()
}

// Reset resets the request counter.
func (p *MockOCRProvider) Reset() {
	p.requestCount.Store(0)
}

// Verify interface
var _ OCRProvider = (*MockOCRProvider)(nil)
