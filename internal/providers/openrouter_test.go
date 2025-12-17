package providers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestOpenRouterClient_Chat(t *testing.T) {
	t.Run("successful chat", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Verify request
			if r.URL.Path != "/chat/completions" {
				t.Errorf("unexpected path: %s", r.URL.Path)
			}
			if r.Method != "POST" {
				t.Errorf("unexpected method: %s", r.Method)
			}
			if auth := r.Header.Get("Authorization"); auth != "Bearer test-key" {
				t.Errorf("unexpected authorization: %s", auth)
			}

			// Return mock response
			resp := map[string]any{
				"id":    "test-id",
				"model": "anthropic/claude-3.5-sonnet",
				"choices": []map[string]any{
					{
						"message": map[string]any{
							"role":    "assistant",
							"content": "Hello! How can I help you?",
						},
						"finish_reason": "stop",
					},
				},
				"usage": map[string]int{
					"prompt_tokens":     10,
					"completion_tokens": 8,
					"total_tokens":      18,
				},
			}

			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.Chat(context.Background(), &ChatRequest{
			Messages: []Message{
				{Role: "user", Content: "Hello"},
			},
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if !result.Success {
			t.Error("expected Success = true")
		}
		if result.Content != "Hello! How can I help you?" {
			t.Errorf("Content = %q", result.Content)
		}
		if result.TotalTokens != 18 {
			t.Errorf("TotalTokens = %d, want 18", result.TotalTokens)
		}
	})

	t.Run("vision message with images", func(t *testing.T) {
		var receivedContent any
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var req openRouterRequest
			json.NewDecoder(r.Body).Decode(&req)

			// Capture the content to verify image handling
			if len(req.Messages) > 0 {
				receivedContent = req.Messages[0].Content
			}

			resp := map[string]any{
				"id":    "test-id",
				"model": "anthropic/claude-3.5-sonnet",
				"choices": []map[string]any{
					{
						"message": map[string]any{
							"role":    "assistant",
							"content": "I see an image",
						},
					},
				},
				"usage": map[string]int{
					"prompt_tokens": 100,
				},
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.Chat(context.Background(), &ChatRequest{
			Messages: []Message{
				{
					Role:    "user",
					Content: "What's in this image?",
					Images:  [][]byte{[]byte("fake-image-data")},
				},
			},
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if !result.Success {
			t.Error("expected Success = true")
		}

		// Verify content was sent as array with image_url
		contentSlice, ok := receivedContent.([]any)
		if !ok {
			t.Fatalf("expected content to be array, got %T", receivedContent)
		}
		if len(contentSlice) != 2 {
			t.Errorf("expected 2 content items, got %d", len(contentSlice))
		}
	})

	t.Run("structured output", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			resp := map[string]any{
				"id":    "test-id",
				"model": "test-model",
				"choices": []map[string]any{
					{
						"message": map[string]any{
							"role":    "assistant",
							"content": `{"name": "test", "value": 123}`,
						},
					},
				},
				"usage": map[string]int{},
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.Chat(context.Background(), &ChatRequest{
			Messages: []Message{{Role: "user", Content: "test"}},
			ResponseFormat: &ResponseFormat{
				Type: "json_schema",
			},
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if result.ParsedJSON == nil {
			t.Error("expected ParsedJSON to be set")
		}
	})

	t.Run("tool calls", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			resp := map[string]any{
				"id":    "test-id",
				"model": "test-model",
				"choices": []map[string]any{
					{
						"message": map[string]any{
							"role": "assistant",
							"tool_calls": []map[string]any{
								{
									"id":   "call_123",
									"type": "function",
									"function": map[string]string{
										"name":      "get_weather",
										"arguments": `{"location": "NYC"}`,
									},
								},
							},
						},
					},
				},
				"usage": map[string]int{},
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		tools := []Tool{
			{
				Type: "function",
				Function: ToolFunction{
					Name:        "get_weather",
					Description: "Get weather for a location",
				},
			},
		}

		result, err := client.ChatWithTools(context.Background(), &ChatRequest{
			Messages: []Message{{Role: "user", Content: "What's the weather in NYC?"}},
		}, tools)

		if err != nil {
			t.Fatalf("ChatWithTools() error = %v", err)
		}
		if len(result.ToolCalls) == 0 {
			t.Fatal("expected tool calls")
		}
		if result.ToolCalls[0].Function.Name != "get_weather" {
			t.Errorf("tool name = %s, want get_weather", result.ToolCalls[0].Function.Name)
		}
	})

	t.Run("API error", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusTooManyRequests)
			w.Write([]byte(`{"error": {"message": "Rate limit exceeded"}}`))
		}))
		defer server.Close()

		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.Chat(context.Background(), &ChatRequest{
			Messages: []Message{{Role: "user", Content: "test"}},
		})

		if err == nil {
			t.Error("expected error")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
		if result.ErrorType != "http_error" {
			t.Errorf("ErrorType = %s, want http_error", result.ErrorType)
		}
	})

	t.Run("context cancellation", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			time.Sleep(100 * time.Millisecond)
			w.WriteHeader(http.StatusOK)
		}))
		defer server.Close()

		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		_, err := client.Chat(ctx, &ChatRequest{
			Messages: []Message{{Role: "user", Content: "test"}},
		})

		if err == nil {
			t.Error("expected error from cancelled context")
		}
	})
}

func TestOpenRouterClient_Config(t *testing.T) {
	t.Run("defaults", func(t *testing.T) {
		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey: "test-key",
		})

		if client.Name() != OpenRouterName {
			t.Errorf("Name() = %s, want %s", client.Name(), OpenRouterName)
		}
		if client.baseURL != OpenRouterBaseURL {
			t.Errorf("baseURL = %s, want %s", client.baseURL, OpenRouterBaseURL)
		}
		if client.defaultModel != "anthropic/claude-3.5-sonnet" {
			t.Errorf("defaultModel = %s", client.defaultModel)
		}
	})

	t.Run("rate limit properties", func(t *testing.T) {
		client := NewOpenRouterClient(OpenRouterConfig{
			APIKey:     "test-key",
			RPS:        50.0,
			MaxRetries: 5,
			RetryDelay: 2 * time.Second,
		})

		if client.RequestsPerSecond() != 50.0 {
			t.Errorf("RequestsPerSecond() = %f, want 50.0", client.RequestsPerSecond())
		}
		if client.MaxRetries() != 5 {
			t.Errorf("MaxRetries() = %d, want 5", client.MaxRetries())
		}
		if client.RetryDelayBase() != 2*time.Second {
			t.Errorf("RetryDelayBase() = %v, want 2s", client.RetryDelayBase())
		}
	})

	t.Run("interface compliance", func(t *testing.T) {
		var _ LLMClient = (*OpenRouterClient)(nil)
	})
}

// TestOpenRouterIntegration runs real LLM calls against the OpenRouter API.
// Requires OPENROUTER_API_KEY environment variable to be set.
func TestOpenRouterIntegration(t *testing.T) {
	cfg := LoadTestConfig()
	if !cfg.HasOpenRouter() {
		t.Skip("OPENROUTER_API_KEY not set - skipping integration test")
	}

	client := cfg.NewOpenRouterClient()

	t.Run("simple chat", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()

		result, err := client.Chat(ctx, &ChatRequest{
			Model: "x-ai/grok-4.1-fast",
			Messages: []Message{
				{Role: "user", Content: "Say 'hello' and nothing else."},
			},
			MaxTokens:   10,
			Temperature: 0,
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if !result.Success {
			t.Errorf("Chat failed: %s", result.ErrorMessage)
		}
		if result.Content == "" {
			t.Error("expected non-empty content")
		}
		t.Logf("Response: %q", result.Content)
		t.Logf("Model: %s", result.ModelUsed)
		t.Logf("Tokens: %d prompt, %d completion", result.PromptTokens, result.CompletionTokens)
		t.Logf("Time: %v", result.ExecutionTime)
	})

	t.Run("structured output", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()

		// Use json_object format with explicit instructions for better compatibility
		result, err := client.Chat(ctx, &ChatRequest{
			Model: "x-ai/grok-4.1-fast",
			Messages: []Message{
				{Role: "system", Content: "You are a helpful assistant that responds only with valid JSON. No explanations, no markdown, just the JSON object."},
				{Role: "user", Content: `Return exactly this JSON: {"greeting": "hello", "count": 42}`},
			},
			ResponseFormat: &ResponseFormat{
				Type: "json_object",
			},
			MaxTokens:   50,
			Temperature: 0,
		})

		if err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
		if !result.Success {
			t.Errorf("Chat failed: %s", result.ErrorMessage)
		}
		t.Logf("Response: %s", result.Content)

		// Verify it's valid JSON
		var parsed map[string]any
		if err := json.Unmarshal([]byte(result.Content), &parsed); err != nil {
			t.Errorf("Response is not valid JSON: %v", err)
		} else {
			t.Logf("Parsed JSON: %+v", parsed)
		}
	})
}
