package providers

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// chandraStub serves an OpenAI-compatible chat endpoint returning markdown,
// recording the chat request body so tests can assert the image was sent.
func chandraStub(t *testing.T, markdown string, capture *[]byte) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/models":
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{"object":"list","data":[{"id":"chandra"}]}`))
		case "/chat/completions":
			if capture != nil {
				*capture, _ = io.ReadAll(r.Body)
			}
			resp := map[string]any{
				"id":    "x",
				"model": "datalab-to/chandra-ocr-2",
				"choices": []any{map[string]any{
					"message":       map[string]any{"role": "assistant", "content": markdown},
					"finish_reason": "stop",
				}},
				"usage": map[string]any{"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
			}
			w.Header().Set("Content-Type", "application/json")
			_ = json.NewEncoder(w).Encode(resp)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
}

func TestChandraOCRClient_ProcessImage(t *testing.T) {
	var body []byte
	srv := chandraStub(t, "# Chapter One\n\nSome text.", &body)
	defer srv.Close()

	c := NewChandraOCRClient(ChandraOCRConfig{BaseURLs: []string{srv.URL}})
	if c.Name() != ChandraOCRName {
		t.Fatalf("Name() = %q, want %q", c.Name(), ChandraOCRName)
	}

	res, err := c.ProcessImage(context.Background(), []byte("fake-jpeg-bytes"), 1)
	if err != nil {
		t.Fatalf("ProcessImage() error = %v", err)
	}
	if !res.Success {
		t.Fatalf("Success = false, err=%s", res.ErrorMessage)
	}
	if res.Text != "# Chapter One\n\nSome text." {
		t.Fatalf("Text = %q, want the markdown", res.Text)
	}
	if res.CostUSD != 0 {
		t.Fatalf("CostUSD = %v, want 0 for local OCR", res.CostUSD)
	}
	// The page image must be sent as an image_url part in the chat request.
	if !strings.Contains(string(body), "image_url") || !strings.Contains(string(body), "data:image") {
		t.Fatalf("chat request did not include the page image; body=%s", body)
	}
}

func TestChandraOCRClient_HealthCheck(t *testing.T) {
	srv := chandraStub(t, "x", nil)
	defer srv.Close()
	c := NewChandraOCRClient(ChandraOCRConfig{BaseURLs: []string{srv.URL}})
	if err := c.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
}

func TestCreateOCRProvider_Chandra(t *testing.T) {
	srv := chandraStub(t, "x", nil)
	defer srv.Close()
	p := createOCRProvider(OCRProviderConfig{Type: "chandra", BaseURLs: []string{srv.URL}})
	if p == nil {
		t.Fatal("expected non-nil chandra OCR provider")
	}
	if err := p.HealthCheck(context.Background()); err != nil {
		t.Fatalf("HealthCheck() error = %v", err)
	}
}

var _ OCRProvider = (*ChandraOCRClient)(nil)
