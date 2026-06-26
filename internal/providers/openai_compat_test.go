package providers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
)

// chatCompletionStub returns a minimal OpenAI-compatible chat completion response
// (as a local vLLM server would), recording the last request seen.
func chatCompletionStub(t *testing.T, onRequest func(path string, header http.Header, body []byte)) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if onRequest != nil {
			onRequest(r.URL.Path, r.Header.Clone(), body)
		}
		switch r.URL.Path {
		case "/models":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"object":"list","data":[{"id":"m"}]}`))
		case "/chat/completions":
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"id":"x","model":"m","choices":[{"message":{"role":"assistant","content":"hi"},"finish_reason":"stop"}],"usage":{"prompt_tokens":1,"completion_tokens":2,"total_tokens":3}}`))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

func TestOpenAICompatClient_Identity(t *testing.T) {
	c := NewOpenAICompatClient(OpenAICompatConfig{BaseURLs: []string{"http://spark-1:8000/v1"}})
	if c.Name() != OpenAICompatName {
		t.Fatalf("Name() = %q, want %q", c.Name(), OpenAICompatName)
	}
	custom := NewOpenAICompatClient(OpenAICompatConfig{Name: "local-qwen", BaseURLs: []string{"http://spark-1:8000/v1"}})
	if custom.Name() != "local-qwen" {
		t.Fatalf("Name() = %q, want local-qwen", custom.Name())
	}
}

func TestOpenAICompatClient_HealthCheckHitsModels(t *testing.T) {
	var gotPath string
	var gotAuth string
	srv := chatCompletionStub(t, func(path string, header http.Header, _ []byte) {
		gotPath = path
		gotAuth = header.Get("Authorization")
	})
	defer srv.Close()

	c := NewOpenAICompatClient(OpenAICompatConfig{BaseURLs: []string{srv.URL}}) // keyless
	if err := c.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
	if gotPath != "/models" {
		t.Fatalf("health check hit %q, want /models", gotPath)
	}
	if gotAuth != "" {
		t.Fatalf("keyless client must not send Authorization, got %q", gotAuth)
	}
}

func TestOpenAICompatClient_ChatOmitsVendorBitsAndZeroCost(t *testing.T) {
	var gotPath string
	var gotHeader http.Header
	var gotBody []byte
	srv := chatCompletionStub(t, func(path string, header http.Header, body []byte) {
		if path == "/chat/completions" {
			gotPath, gotHeader, gotBody = path, header, body
		}
	})
	defer srv.Close()

	c := NewOpenAICompatClient(OpenAICompatConfig{BaseURLs: []string{srv.URL}, DefaultModel: "m"})
	res, err := c.Chat(context.Background(), &ChatRequest{
		Messages: []Message{{Role: "user", Content: "hello"}},
	})
	if err != nil {
		t.Fatalf("Chat() error = %v", err)
	}
	if !res.Success {
		t.Fatalf("Chat() Success = false, err=%s", res.ErrorMessage)
	}
	if gotPath != "/chat/completions" {
		t.Fatalf("chat hit %q", gotPath)
	}
	if res.Provider != OpenAICompatName {
		t.Fatalf("result.Provider = %q, want %q", res.Provider, OpenAICompatName)
	}
	if res.CostUSD != 0 {
		t.Fatalf("CostUSD = %v, want 0 for local inference", res.CostUSD)
	}
	if gotHeader.Get("HTTP-Referer") != "" || gotHeader.Get("X-Title") != "" {
		t.Fatalf("openai-compat client must not send OpenRouter vendor headers")
	}
	// The OpenRouter-specific `usage.include` request flag must not be sent.
	var bodyMap map[string]any
	if err := json.Unmarshal(gotBody, &bodyMap); err != nil {
		t.Fatalf("request body not JSON: %v", err)
	}
	if _, ok := bodyMap["usage"]; ok {
		t.Fatalf("openai-compat client must not send the `usage` request field; body=%s", gotBody)
	}
}

func TestOpenAICompatClient_RoundRobinsAcrossEndpoints(t *testing.T) {
	var hitsA, hitsB atomic.Int64
	srvA := chatCompletionStub(t, func(path string, _ http.Header, _ []byte) {
		if path == "/chat/completions" {
			hitsA.Add(1)
		}
	})
	defer srvA.Close()
	srvB := chatCompletionStub(t, func(path string, _ http.Header, _ []byte) {
		if path == "/chat/completions" {
			hitsB.Add(1)
		}
	})
	defer srvB.Close()

	c := NewOpenAICompatClient(OpenAICompatConfig{BaseURLs: []string{srvA.URL, srvB.URL}, DefaultModel: "m"})
	for i := 0; i < 4; i++ {
		if _, err := c.Chat(context.Background(), &ChatRequest{Messages: []Message{{Role: "user", Content: "x"}}}); err != nil {
			t.Fatalf("Chat() error = %v", err)
		}
	}
	if hitsA.Load() != 2 || hitsB.Load() != 2 {
		t.Fatalf("round-robin uneven: A=%d B=%d, want 2/2", hitsA.Load(), hitsB.Load())
	}
}

func TestOpenAICompat_MaxConcurrencyConfigurable(t *testing.T) {
	def := NewOpenAICompatClient(OpenAICompatConfig{BaseURLs: []string{"http://x:8000/v1"}})
	if def.MaxConcurrency() != 0 {
		t.Fatalf("default MaxConcurrency = %d, want 0 (provider default)", def.MaxConcurrency())
	}
	llm := createLLMClient(LLMProviderConfig{Type: "openai-compat", BaseURLs: []string{"http://x:8000/v1"}, MaxConcurrency: 32})
	if llm.MaxConcurrency() != 32 {
		t.Fatalf("LLM MaxConcurrency = %d, want 32", llm.MaxConcurrency())
	}
	ocr := createOCRProvider(OCRProviderConfig{Type: "chandra", BaseURLs: []string{"http://x:8001/v1"}, MaxConcurrency: 32})
	if ocr.MaxConcurrency() != 32 {
		t.Fatalf("OCR MaxConcurrency = %d, want 32", ocr.MaxConcurrency())
	}
	// OpenRouter preset must remain on the provider default (0).
	or := NewOpenRouterClient(OpenRouterConfig{APIKey: "k"})
	if or.MaxConcurrency() != 0 {
		t.Fatalf("openrouter MaxConcurrency = %d, want 0", or.MaxConcurrency())
	}
}

func TestCreateLLMClient_OpenAICompat(t *testing.T) {
	srv := chatCompletionStub(t, nil)
	defer srv.Close()

	client := createLLMClient(LLMProviderConfig{
		Type:     "openai-compat",
		Model:    "nvidia/Qwen3.6-35B-A3B-NVFP4",
		BaseURLs: []string{srv.URL},
	})
	if client == nil {
		t.Fatal("expected non-nil openai-compat client")
	}
	if err := client.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
}
