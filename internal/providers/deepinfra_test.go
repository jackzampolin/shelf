package providers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"os"
	"strings"
	"testing"
	"time"
)

func TestDeepInfraOCRClient_ProcessImage(t *testing.T) {
	t.Run("successful OCR", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Verify request
			if r.URL.Path != "/chat/completions" {
				t.Errorf("unexpected path: %s", r.URL.Path)
			}
			if r.Method != "POST" {
				t.Errorf("unexpected method: %s", r.Method)
			}
			if ct := r.Header.Get("Content-Type"); ct != "application/json" {
				t.Errorf("unexpected content-type: %s", ct)
			}
			if auth := r.Header.Get("Authorization"); auth != "Bearer test-key" {
				t.Errorf("unexpected authorization: %s", auth)
			}

			// Decode request to verify structure
			var req deepInfraRequest
			if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
				t.Errorf("failed to decode request: %v", err)
			}
			if req.Model != "PaddlePaddle/PaddleOCR-VL-0.9B" {
				t.Errorf("unexpected model: %s", req.Model)
			}
			if len(req.Messages) != 1 {
				t.Errorf("expected 1 message, got %d", len(req.Messages))
			}

			// Return mock response
			resp := deepInfraResponse{
				ID:    "test-id",
				Model: "PaddlePaddle/PaddleOCR-VL-0.9B",
				Choices: []struct {
					Index   int `json:"index"`
					Message struct {
						Role    string `json:"role"`
						Content string `json:"content"`
					} `json:"message"`
					FinishReason string `json:"finish_reason"`
				}{
					{
						Index: 0,
						Message: struct {
							Role    string `json:"role"`
							Content string `json:"content"`
						}{
							Role:    "assistant",
							Content: "# Chapter 1\n\nThis is the extracted text from DeepInfra.",
						},
						FinishReason: "stop",
					},
				},
				Usage: struct {
					PromptTokens     int     `json:"prompt_tokens"`
					CompletionTokens int     `json:"completion_tokens"`
					TotalTokens      int     `json:"total_tokens"`
					EstimatedCost    float64 `json:"estimated_cost,omitempty"`
				}{
					PromptTokens:     100,
					CompletionTokens: 50,
					TotalTokens:      150,
					EstimatedCost:    0.0015,
				},
			}

			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.ProcessImage(context.Background(), []byte("fake image data"), 1)

		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}
		if !result.Success {
			t.Error("expected Success = true")
		}
		if result.Text != "# Chapter 1\n\nThis is the extracted text from DeepInfra." {
			t.Errorf("unexpected text: %q", result.Text)
		}
		if result.CostUSD != 0.0015 {
			t.Errorf("CostUSD = %f, want 0.0015", result.CostUSD)
		}
		if result.ExecutionTime == 0 {
			t.Error("expected non-zero ExecutionTime")
		}

		// Verify metadata
		if result.Metadata == nil {
			t.Fatal("expected metadata")
		}
		if result.Metadata["model_used"] != "PaddlePaddle/PaddleOCR-VL-0.9B" {
			t.Errorf("model_used = %v", result.Metadata["model_used"])
		}
		if result.Metadata["total_tokens"] != 150 {
			t.Errorf("total_tokens = %v", result.Metadata["total_tokens"])
		}
	})

	t.Run("empty choices response", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			resp := deepInfraResponse{
				ID:      "test-id",
				Model:   "PaddlePaddle/PaddleOCR-VL-0.9B",
				Choices: []struct {
					Index   int `json:"index"`
					Message struct {
						Role    string `json:"role"`
						Content string `json:"content"`
					} `json:"message"`
					FinishReason string `json:"finish_reason"`
				}{}, // Empty choices
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.ProcessImage(context.Background(), []byte("fake"), 1)

		if err == nil {
			t.Error("expected error for empty choices")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
		if result.ErrorMessage == "" {
			t.Error("expected error message")
		}
	})

	t.Run("API error response", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.WriteHeader(http.StatusBadRequest)
			json.NewEncoder(w).Encode(map[string]any{
				"error": map[string]string{
					"message": "Invalid image format",
					"type":    "invalid_request_error",
				},
			})
		}))
		defer server.Close()

		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		result, err := client.ProcessImage(context.Background(), []byte("fake"), 1)

		if err == nil {
			t.Error("expected error for API error response")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
		if !strings.Contains(err.Error(), "Invalid image format") {
			t.Errorf("expected error message to contain 'Invalid image format', got: %v", err)
		}
	})

	t.Run("context cancellation", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			time.Sleep(100 * time.Millisecond)
			w.WriteHeader(http.StatusOK)
		}))
		defer server.Close()

		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
		})

		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		result, err := client.ProcessImage(ctx, []byte("fake"), 1)

		if err == nil {
			t.Error("expected error from cancelled context")
		}
		if result.Success {
			t.Error("expected Success = false")
		}
	})

	t.Run("custom model and prompt", func(t *testing.T) {
		var receivedModel string
		var receivedPrompt string
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			var req deepInfraRequest
			json.NewDecoder(r.Body).Decode(&req)
			receivedModel = req.Model

			// Extract prompt from first content item
			if len(req.Messages) > 0 {
				contents := req.Messages[0].Content.([]any)
				if len(contents) > 0 {
					textContent := contents[0].(map[string]any)
					receivedPrompt = textContent["text"].(string)
				}
			}

			resp := deepInfraResponse{
				ID:    "test-id",
				Model: req.Model,
				Choices: []struct {
					Index   int `json:"index"`
					Message struct {
						Role    string `json:"role"`
						Content string `json:"content"`
					} `json:"message"`
					FinishReason string `json:"finish_reason"`
				}{
					{
						Message: struct {
							Role    string `json:"role"`
							Content string `json:"content"`
						}{
							Content: "extracted text",
						},
					},
				},
			}
			w.Header().Set("Content-Type", "application/json")
			json.NewEncoder(w).Encode(resp)
		}))
		defer server.Close()

		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:  "test-key",
			BaseURL: server.URL,
			Model:   "Qwen/Qwen2-VL-72B-Instruct",
			Prompt:  "Custom OCR prompt for testing.",
		})

		_, err := client.ProcessImage(context.Background(), []byte("fake"), 1)
		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}

		if receivedModel != "Qwen/Qwen2-VL-72B-Instruct" {
			t.Errorf("expected model Qwen/Qwen2-VL-72B-Instruct, got %s", receivedModel)
		}
		if receivedPrompt != "Custom OCR prompt for testing." {
			t.Errorf("expected custom prompt, got %s", receivedPrompt)
		}
	})
}

func TestDeepInfraOCRClient_Config(t *testing.T) {
	t.Run("config defaults", func(t *testing.T) {
		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey: "test-key",
		})

		if client.Name() != DeepInfraOCRName {
			t.Errorf("Name() = %s, want %s", client.Name(), DeepInfraOCRName)
		}
		if client.baseURL != DeepInfraBaseURL {
			t.Errorf("baseURL = %s, want %s", client.baseURL, DeepInfraBaseURL)
		}
		if client.model != "PaddlePaddle/PaddleOCR-VL-0.9B" {
			t.Errorf("model = %s, want PaddlePaddle/PaddleOCR-VL-0.9B", client.model)
		}
		if client.prompt != DeepInfraDefaultOCRPrompt {
			t.Errorf("prompt = %s, want default", client.prompt)
		}
		if client.temperature != 0.1 {
			t.Errorf("temperature = %f, want 0.1", client.temperature)
		}
		if client.maxTokens != 8000 {
			t.Errorf("maxTokens = %d, want 8000", client.maxTokens)
		}
	})

	t.Run("rate limit properties", func(t *testing.T) {
		client := NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:    "test-key",
			RateLimit: 5.0,
		})

		if client.RequestsPerSecond() != 5.0 {
			t.Errorf("RequestsPerSecond() = %f, want 5.0", client.RequestsPerSecond())
		}
		if client.MaxRetries() != 3 {
			t.Errorf("MaxRetries() = %d, want 3", client.MaxRetries())
		}
		if client.RetryDelayBase() != 2*time.Second {
			t.Errorf("RetryDelayBase() = %v, want 2s", client.RetryDelayBase())
		}
	})

	t.Run("interface compliance", func(t *testing.T) {
		var _ OCRProvider = (*DeepInfraOCRClient)(nil)
	})
}

// TestDeepInfraOCRIntegration runs real OCR against the DeepInfra API.
// Requires DEEPINFRA_API_KEY environment variable to be set.
// Uses test fixtures from testdata/ directory.
// Skipped by default - run with: go test -run TestDeepInfraOCRIntegration ./internal/providers
func TestDeepInfraOCRIntegration(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}
	cfg := LoadTestConfig()
	if !cfg.HasDeepInfra() {
		t.Skip("DEEPINFRA_API_KEY not set")
	}

	client := cfg.NewDeepInfraOCRClient()

	// Find test images
	testdataDir := filepath.Join("testdata")
	entries, err := os.ReadDir(testdataDir)
	if err != nil {
		t.Skipf("testdata directory not found: %v", err)
	}

	var testImages []string
	for _, e := range entries {
		if strings.HasSuffix(e.Name(), ".png") {
			testImages = append(testImages, filepath.Join(testdataDir, e.Name()))
		}
	}

	if len(testImages) == 0 {
		t.Skip("no test images found in testdata/")
	}

	t.Run("real OCR", func(t *testing.T) {
		// Just test one image to minimize cost
		imagePath := testImages[0]
		imageData, err := os.ReadFile(imagePath)
		if err != nil {
			t.Fatalf("failed to read test image: %v", err)
		}

		t.Logf("Testing DeepInfra OCR on %s (%d bytes)", filepath.Base(imagePath), len(imageData))

		ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
		defer cancel()

		result, err := client.ProcessImage(ctx, imageData, 1)
		if err != nil {
			t.Fatalf("ProcessImage() error = %v", err)
		}

		// Verify success
		if !result.Success {
			t.Errorf("OCR failed: %s", result.ErrorMessage)
		}

		// Verify we got text
		if len(result.Text) == 0 {
			t.Error("expected non-empty text")
		}
		t.Logf("Extracted %d characters", len(result.Text))

		// Log first 500 chars of output
		preview := result.Text
		if len(preview) > 500 {
			preview = preview[:500] + "..."
		}
		t.Logf("Text preview:\n%s", preview)

		// Verify cost tracking
		t.Logf("Cost: $%.6f", result.CostUSD)

		// Verify timing
		if result.ExecutionTime == 0 {
			t.Error("expected non-zero execution time")
		}
		t.Logf("Execution time: %v", result.ExecutionTime)

		// Verify metadata
		if result.Metadata == nil {
			t.Error("expected metadata")
		}
		if result.Metadata["model_used"] == nil {
			t.Error("expected model_used in metadata")
		}
		t.Logf("Model: %v", result.Metadata["model_used"])
		t.Logf("Tokens: %v", result.Metadata["total_tokens"])
	})
}
