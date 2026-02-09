package providers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

func TestOpenAITTSGenerateSuccess(t *testing.T) {
	var payload map[string]any

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/audio/speech" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		if r.Method != http.MethodPost {
			t.Fatalf("unexpected method: %s", r.Method)
		}

		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Fatalf("read body: %v", err)
		}
		if err := json.Unmarshal(body, &payload); err != nil {
			t.Fatalf("unmarshal body: %v", err)
		}

		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("mp3-bytes"))
	}))
	defer server.Close()

	client := NewOpenAITTSClient(OpenAITTSConfig{
		APIKey:       "test-key",
		Model:        "gpt-4o-mini-tts",
		Voice:        "onyx",
		Instructions: "Default instructions",
		BaseURL:      server.URL,
	})

	result, err := client.Generate(context.Background(), &TTSRequest{
		Text:         "Hello world.",
		Format:       "mp3",
		Instructions: "Narrate calmly.",
	})
	if err != nil {
		t.Fatalf("Generate() error = %v", err)
	}
	if !result.Success {
		t.Fatalf("expected success result")
	}
	if string(result.Audio) != "mp3-bytes" {
		t.Fatalf("unexpected audio bytes: %q", string(result.Audio))
	}
	if result.CostUSD <= 0 {
		t.Fatalf("expected non-zero cost estimate, got %f", result.CostUSD)
	}
	if got, _ := payload["model"].(string); got != "gpt-4o-mini-tts" {
		t.Fatalf("expected model gpt-4o-mini-tts, got %q", got)
	}
	if got, _ := payload["voice"].(string); got != "onyx" {
		t.Fatalf("expected voice onyx, got %q", got)
	}
	if got, _ := payload["response_format"].(string); got != "mp3" {
		t.Fatalf("expected response_format mp3, got %q", got)
	}
	if got, _ := payload["instructions"].(string); got != "Narrate calmly." {
		t.Fatalf("expected instructions override, got %q", got)
	}
}

func TestOpenAITTSGenerateRateLimit(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Retry-After", "3")
		w.WriteHeader(http.StatusTooManyRequests)
		_, _ = w.Write([]byte(`{"error":{"message":"rate limit","type":"rate_limit_error","param":"","code":"rate_limit"}}`))
	}))
	defer server.Close()

	client := NewOpenAITTSClient(OpenAITTSConfig{
		APIKey:  "test-key",
		Model:   "tts-1-hd",
		Voice:   "onyx",
		BaseURL: server.URL,
	})

	_, err := client.Generate(context.Background(), &TTSRequest{
		Text:   "Hello world.",
		Format: "mp3",
	})
	if err == nil {
		t.Fatal("expected error for 429 response")
	}
	rle, ok := IsRateLimitError(err)
	if !ok {
		t.Fatalf("expected RateLimitError, got %T: %v", err, err)
	}
	if rle.StatusCode != http.StatusTooManyRequests {
		t.Fatalf("expected status 429, got %d", rle.StatusCode)
	}
	if rle.RetryAfter != 3*time.Second {
		t.Fatalf("expected RetryAfter=3s, got %v", rle.RetryAfter)
	}
}

func TestOpenAITTSHealthCheck(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/models" {
			t.Fatalf("unexpected path: %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"object":"list","data":[{"id":"tts-1","object":"model","created":1,"owned_by":"openai"}]}`))
	}))
	defer server.Close()

	client := NewOpenAITTSClient(OpenAITTSConfig{
		APIKey:  "test-key",
		Model:   "tts-1-hd",
		Voice:   "onyx",
		BaseURL: server.URL,
	})

	if err := client.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
}

func TestOpenAITTSListVoices(t *testing.T) {
	client := NewOpenAITTSClient(OpenAITTSConfig{
		APIKey: "test-key",
	})

	voices, err := client.ListVoices(context.Background())
	if err != nil {
		t.Fatalf("ListVoices() error = %v", err)
	}
	if len(voices) != 13 {
		t.Fatalf("expected 13 voices, got %d", len(voices))
	}
	foundOnyx := false
	for _, v := range voices {
		if v.VoiceID == "onyx" {
			foundOnyx = true
			break
		}
	}
	if !foundOnyx {
		t.Fatal("expected onyx in voice list")
	}
}

func TestOpenAITTSGenerateValidation(t *testing.T) {
	client := NewOpenAITTSClient(OpenAITTSConfig{
		APIKey: "test-key",
	})

	_, err := client.Generate(context.Background(), &TTSRequest{
		Text: "",
	})
	if err == nil {
		t.Fatal("expected validation error for empty text")
	}
	if !strings.Contains(err.Error(), "text is required") {
		t.Fatalf("unexpected error: %v", err)
	}
}
