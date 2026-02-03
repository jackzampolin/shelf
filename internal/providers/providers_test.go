package providers

import (
	"context"
	"encoding/json"
	"sync"
	"sync/atomic"
	"testing"
	"time"
)

func TestMockClient(t *testing.T) {
	t.Run("chat", func(t *testing.T) {
		c := NewMockClient()
		c.ResponseText = "hello world"

		result, err := c.Chat(context.Background(), &ChatRequest{
			Model: "test-model",
			Messages: []Message{
				{Role: "user", Content: "test"},
			},
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if !result.Success {
			t.Errorf("Success = false, want true")
		}
		if result.Content != "hello world" {
			t.Errorf("Content = %q, want %q", result.Content, "hello world")
		}
		if c.RequestCount() != 1 {
			t.Errorf("RequestCount = %d, want 1", c.RequestCount())
		}
	})

	t.Run("chat with tools", func(t *testing.T) {
		c := NewMockClient()

		tools := []Tool{
			{
				Type: "function",
				Function: ToolFunction{
					Name:        "get_weather",
					Description: "Get weather",
				},
			},
		}

		result, err := c.ChatWithTools(context.Background(), &ChatRequest{
			Messages: []Message{{Role: "user", Content: "test"}},
		}, tools)

		if err != nil {
			t.Fatalf("ChatWithTools() error = %v", err)
		}
		if len(result.ToolCalls) == 0 {
			t.Error("expected tool calls")
		}
		if result.ToolCalls[0].Function.Name != "get_weather" {
			t.Errorf("tool name = %s, want get_weather", result.ToolCalls[0].Function.Name)
		}
	})

	t.Run("structured output", func(t *testing.T) {
		c := NewMockClient()
		c.ResponseJSON = json.RawMessage(`{"key": "value"}`)

		result, err := c.Chat(context.Background(), &ChatRequest{
			Messages: []Message{{Role: "user", Content: "test"}},
			ResponseFormat: &ResponseFormat{
				Type: "json_schema",
			},
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if result.ParsedJSON == nil {
			t.Error("expected ParsedJSON")
		}
	})

	t.Run("failure", func(t *testing.T) {
		c := NewMockClient()
		c.ShouldFail = true

		result, err := c.Chat(context.Background(), &ChatRequest{})
		if err == nil {
			t.Error("expected error, got nil")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
	})

	t.Run("fail after N", func(t *testing.T) {
		c := NewMockClient()
		c.FailAfter = 2

		// First two should succeed
		_, err := c.Chat(context.Background(), &ChatRequest{})
		if err != nil {
			t.Fatalf("first request should succeed: %v", err)
		}
		_, err = c.Chat(context.Background(), &ChatRequest{})
		if err != nil {
			t.Fatalf("second request should succeed: %v", err)
		}

		// Third should fail
		_, err = c.Chat(context.Background(), &ChatRequest{})
		if err == nil {
			t.Error("third request should fail")
		}
	})

	t.Run("respects cancellation", func(t *testing.T) {
		c := NewMockClient()
		c.Latency = 5 * time.Second

		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		_, err := c.Chat(ctx, &ChatRequest{})
		if err != context.Canceled {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	})
}

func TestMockOCRProvider(t *testing.T) {
	t.Run("process image", func(t *testing.T) {
		p := NewMockOCRProvider()
		p.ResponseText = "extracted text"

		result, err := p.ProcessImage(context.Background(), []byte("fake image"), 1)

		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}
		if !result.Success {
			t.Error("expected success")
		}
		if result.Text == "" {
			t.Error("expected non-empty text")
		}
	})

	t.Run("rate limit properties", func(t *testing.T) {
		p := NewMockOCRProvider()

		if p.RequestsPerSecond() != 10.0 {
			t.Errorf("RequestsPerSecond = %f, want 10", p.RequestsPerSecond())
		}
		if p.MaxRetries() != 3 {
			t.Errorf("MaxRetries = %d, want 3", p.MaxRetries())
		}
		if p.RetryDelayBase() != time.Second {
			t.Errorf("RetryDelayBase = %v, want 1s", p.RetryDelayBase())
		}
	})
}

func TestRateLimiter(t *testing.T) {
	t.Run("allows initial requests", func(t *testing.T) {
		limiter := NewRateLimiter(600) // 10 per second

		// Should allow 5 requests quickly
		start := time.Now()
		for i := 0; i < 5; i++ {
			if err := limiter.Wait(context.Background()); err != nil {
				t.Fatalf("request %d failed: %v", i, err)
			}
		}
		elapsed := time.Since(start)

		// Should complete quickly since we have burst capacity
		if elapsed > time.Second {
			t.Errorf("took too long: %v", elapsed)
		}
	})

	t.Run("try consume", func(t *testing.T) {
		limiter := NewRateLimiter(60)

		// Should succeed initially
		if !limiter.TryConsume() {
			t.Error("first TryConsume should succeed")
		}
	})

	t.Run("status", func(t *testing.T) {
		limiter := NewRateLimiter(60.0) // 60 RPS

		status := limiter.Status()

		if status.RPS != 60.0 {
			t.Errorf("RPS = %f, want 60.0", status.RPS)
		}
		if status.TokensAvailable <= 0 {
			t.Error("expected positive tokens available")
		}
	})

	t.Run("record 429", func(t *testing.T) {
		limiter := NewRateLimiter(60)

		limiter.Record429(time.Second)

		status := limiter.Status()
		if status.Last429Time.IsZero() {
			t.Error("Last429Time should be set")
		}
	})

	t.Run("respects cancellation", func(t *testing.T) {
		// Create limiter with very low rate
		limiter := NewRateLimiter(1) // 1 per second

		// Consume the one allowed token
		limiter.Wait(context.Background())

		// Cancel context immediately
		ctx, cancel := context.WithCancel(context.Background())
		cancel()

		err := limiter.Wait(ctx)
		if err != context.Canceled {
			t.Errorf("expected context.Canceled, got %v", err)
		}
	})

	t.Run("concurrent requests", func(t *testing.T) {
		limiter := NewRateLimiter(6000) // 100 per second

		var wg sync.WaitGroup
		var errors atomic.Int32

		// Fire 10 concurrent requests
		for i := 0; i < 10; i++ {
			wg.Add(1)
			go func() {
				defer wg.Done()
				if err := limiter.Wait(context.Background()); err != nil {
					errors.Add(1)
				}
			}()
		}

		wg.Wait()

		if errors.Load() > 0 {
			t.Errorf("had %d errors", errors.Load())
		}

		status := limiter.Status()
		if status.TotalConsumed != 10 {
			t.Errorf("TotalConsumed = %d, want 10", status.TotalConsumed)
		}
	})
}

// TestTestConfig verifies the test helper works correctly.
func TestTestConfig(t *testing.T) {
	t.Run("loads from environment", func(t *testing.T) {
		cfg := LoadTestConfig()
		// Just verify it doesn't panic - actual values depend on environment
		_ = cfg.HasOpenRouter()
		_ = cfg.HasMistral()
		_ = cfg.HasAnyOCR()
		_ = cfg.HasAnyLLM()
	})

	t.Run("ToRegistryConfig", func(t *testing.T) {
		cfg := LoadTestConfig()
		regCfg := cfg.ToRegistryConfig()

		// Verify structure is correct
		if regCfg.OCRProviders == nil {
			t.Error("OCRProviders should not be nil")
		}
		if regCfg.LLMProviders == nil {
			t.Error("LLMProviders should not be nil")
		}
	})
}
