package config

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
)

// mockDefraServer creates a test server that simulates DefraDB responses.
func mockDefraServer(t *testing.T, handler func(query string) map[string]any) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/health-check" {
			w.WriteHeader(http.StatusOK)
			return
		}

		var req defra.GQLRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			t.Fatalf("failed to decode request: %v", err)
		}

		data := handler(req.Query)
		resp := defra.GQLResponse{Data: data}

		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(resp)
	}))
}

func TestDefraStore_Get(t *testing.T) {
	server := mockDefraServer(t, func(query string) map[string]any {
		if strings.Contains(query, `key: {_eq: "providers.ocr.mistral.type"}`) {
			return map[string]any{
				"Config": []any{
					map[string]any{
						"_docID":      "doc123",
						"key":         "providers.ocr.mistral.type",
						"value":       `"mistral-ocr"`,
						"description": "OCR provider type",
					},
				},
			}
		}
		return map[string]any{"Config": []any{}}
	})
	defer server.Close()

	client := defra.NewClient(server.URL)
	store := NewStore(client)

	t.Run("existing_key", func(t *testing.T) {
		entry, err := store.Get(t.Context(), "providers.ocr.mistral.type")
		if err != nil {
			t.Fatalf("Get() error = %v", err)
		}
		if entry == nil {
			t.Fatal("Get() returned nil for existing key")
		}
		if entry.Key != "providers.ocr.mistral.type" {
			t.Errorf("Key = %q, want %q", entry.Key, "providers.ocr.mistral.type")
		}
		if entry.Value != "mistral-ocr" {
			t.Errorf("Value = %v, want %q", entry.Value, "mistral-ocr")
		}
	})

	t.Run("non_existent_key", func(t *testing.T) {
		entry, err := store.Get(t.Context(), "does.not.exist")
		if err != nil {
			t.Fatalf("Get() error = %v", err)
		}
		if entry != nil {
			t.Errorf("Get() = %v, want nil for non-existent key", entry)
		}
	})
}

func TestDefraStore_GetAll(t *testing.T) {
	server := mockDefraServer(t, func(query string) map[string]any {
		return map[string]any{
			"Config": []any{
				map[string]any{
					"_docID":      "doc1",
					"key":         "providers.ocr.mistral.type",
					"value":       `"mistral-ocr"`,
					"description": "OCR provider type",
				},
				map[string]any{
					"_docID":      "doc2",
					"key":         "providers.llm.openrouter.model",
					"value":       `"gpt-4"`,
					"description": "LLM model name",
				},
			},
		}
	})
	defer server.Close()

	client := defra.NewClient(server.URL)
	store := NewStore(client)

	entries, err := store.GetAll(t.Context())
	if err != nil {
		t.Fatalf("GetAll() error = %v", err)
	}

	if len(entries) != 2 {
		t.Errorf("GetAll() returned %d entries, want 2", len(entries))
	}

	if _, ok := entries["providers.ocr.mistral.type"]; !ok {
		t.Error("GetAll() missing key 'providers.ocr.mistral.type'")
	}
	if _, ok := entries["providers.llm.openrouter.model"]; !ok {
		t.Error("GetAll() missing key 'providers.llm.openrouter.model'")
	}
}

func TestDefraStore_GetByPrefix(t *testing.T) {
	server := mockDefraServer(t, func(query string) map[string]any {
		return map[string]any{
			"Config": []any{
				map[string]any{
					"_docID": "doc1",
					"key":    "providers.ocr.mistral.type",
					"value":  `"mistral-ocr"`,
				},
				map[string]any{
					"_docID": "doc2",
					"key":    "providers.ocr.paddle.type",
					"value":  `"deepinfra"`,
				},
				map[string]any{
					"_docID": "doc3",
					"key":    "providers.llm.openrouter.type",
					"value":  `"openrouter"`,
				},
			},
		}
	})
	defer server.Close()

	client := defra.NewClient(server.URL)
	store := NewStore(client)

	entries, err := store.GetByPrefix(t.Context(), "providers.ocr.")
	if err != nil {
		t.Fatalf("GetByPrefix() error = %v", err)
	}

	if len(entries) != 2 {
		t.Errorf("GetByPrefix('providers.ocr.') returned %d entries, want 2", len(entries))
	}

	// Should not include LLM provider
	if _, ok := entries["providers.llm.openrouter.type"]; ok {
		t.Error("GetByPrefix() should not include non-matching prefix")
	}
}

func TestExtractProviders(t *testing.T) {
	entries := map[string]Entry{
		"providers.ocr.mistral.type":       {Key: "providers.ocr.mistral.type", Value: "mistral-ocr"},
		"providers.ocr.mistral.api_key":    {Key: "providers.ocr.mistral.api_key", Value: "${MISTRAL_API_KEY}"},
		"providers.ocr.mistral.rate_limit": {Key: "providers.ocr.mistral.rate_limit", Value: float64(6)},
		"providers.ocr.mistral.enabled":    {Key: "providers.ocr.mistral.enabled", Value: true},
		"providers.ocr.paddle.type":        {Key: "providers.ocr.paddle.type", Value: "deepinfra"},
		"providers.llm.openrouter.type":    {Key: "providers.llm.openrouter.type", Value: "openrouter"},
		"defaults.max_workers":             {Key: "defaults.max_workers", Value: float64(10)},
	}

	t.Run("extract_ocr_providers", func(t *testing.T) {
		result := extractProviders(entries, "providers.ocr.")

		if len(result) != 2 {
			t.Errorf("extractProviders() returned %d providers, want 2", len(result))
		}

		mistral, ok := result["mistral"]
		if !ok {
			t.Fatal("extractProviders() missing 'mistral' provider")
		}
		if mistral["type"] != "mistral-ocr" {
			t.Errorf("mistral.type = %v, want %q", mistral["type"], "mistral-ocr")
		}
		if mistral["enabled"] != true {
			t.Errorf("mistral.enabled = %v, want true", mistral["enabled"])
		}
	})

	t.Run("extract_llm_providers", func(t *testing.T) {
		result := extractProviders(entries, "providers.llm.")

		if len(result) != 1 {
			t.Errorf("extractProviders() returned %d providers, want 1", len(result))
		}

		openrouter, ok := result["openrouter"]
		if !ok {
			t.Fatal("extractProviders() missing 'openrouter' provider")
		}
		if openrouter["type"] != "openrouter" {
			t.Errorf("openrouter.type = %v, want %q", openrouter["type"], "openrouter")
		}
	})

	t.Run("no_matching_prefix", func(t *testing.T) {
		result := extractProviders(entries, "nonexistent.")
		if len(result) != 0 {
			t.Errorf("extractProviders() with non-matching prefix should return empty map")
		}
	})
}

func TestGetHelpers(t *testing.T) {
	m := map[string]any{
		"string_val": "hello",
		"float_val":  3.14,
		"int_val":    42,
		"bool_val":   true,
	}

	if got := getString(m, "string_val"); got != "hello" {
		t.Errorf("getString() = %q, want %q", got, "hello")
	}
	if got := getString(m, "missing"); got != "" {
		t.Errorf("getString() for missing = %q, want empty", got)
	}

	if got := getFloat(m, "float_val"); got != 3.14 {
		t.Errorf("getFloat() = %v, want %v", got, 3.14)
	}
	if got := getFloat(m, "int_val"); got != 42 {
		t.Errorf("getFloat() for int = %v, want %v", got, 42)
	}

	if got := getBool(m, "bool_val"); got != true {
		t.Errorf("getBool() = %v, want true", got)
	}
	if got := getBool(m, "missing"); got != false {
		t.Errorf("getBool() for missing = %v, want false", got)
	}
}

func TestValidateKey(t *testing.T) {
	tests := []struct {
		name    string
		key     string
		wantErr bool
	}{
		{"valid simple key", "foo", false},
		{"valid dotted key", "providers.ocr.mistral.type", false},
		{"valid with underscore", "defaults.max_workers", false},
		{"valid with hyphen", "my-setting", false},
		{"valid with numbers", "provider1.config2", false},
		{"empty key", "", true},
		{"starts with dot", ".foo", true},
		{"ends with dot", "foo.", true},
		{"contains space", "foo bar", true},
		{"contains special char", "foo@bar", true},
		{"contains slash", "foo/bar", true},
		{"contains colon", "foo:bar", true},
		{"contains quote", "foo\"bar", true},
		{"contains curly brace", "foo{bar}", true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := ValidateKey(tt.key)
			if (err != nil) != tt.wantErr {
				t.Errorf("ValidateKey(%q) error = %v, wantErr %v", tt.key, err, tt.wantErr)
			}
			if err != nil && !errors.Is(err, ErrInvalidKey) {
				t.Errorf("ValidateKey(%q) error should wrap ErrInvalidKey, got %v", tt.key, err)
			}
		})
	}
}
