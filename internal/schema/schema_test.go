package schema

import (
	"context"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
)

func TestAll(t *testing.T) {
	schemas, err := All()
	if err != nil {
		t.Fatalf("All() error = %v", err)
	}

	if len(schemas) == 0 {
		t.Error("expected at least one schema")
	}

	// Verify Job schema exists
	found := false
	for _, s := range schemas {
		if s.Name == "Job" {
			found = true
			if s.SDL == "" {
				t.Error("Job schema SDL is empty")
			}
			if !strings.Contains(s.SDL, "type Job") {
				t.Error("Job schema SDL doesn't contain 'type Job'")
			}
		}
	}

	if !found {
		t.Error("Job schema not found")
	}
}

func TestGet(t *testing.T) {
	t.Run("existing schema", func(t *testing.T) {
		s, err := Get("Job")
		if err != nil {
			t.Fatalf("Get(Job) error = %v", err)
		}
		if s.Name != "Job" {
			t.Errorf("expected name Job, got %s", s.Name)
		}
		if s.SDL == "" {
			t.Error("SDL is empty")
		}
	})

	t.Run("non-existent schema", func(t *testing.T) {
		_, err := Get("NonExistent")
		if err == nil {
			t.Error("expected error for non-existent schema")
		}
	})
}

func TestInitialize(t *testing.T) {
	t.Run("successful initialization", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/api/v0/collections" && r.Method == http.MethodPost {
				w.WriteHeader(http.StatusOK)
				return
			}
			if r.URL.Path == "/api/v0/collections" && r.Method == http.MethodGet {
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`[{"Name":"Job","Fields":[{"Name":"status_reason","Typ":1},{"Name":"heartbeat_at","Typ":1},{"Name":"last_progress_at","Typ":1}]},{"Name":"Page","Fields":[{"Name":"ocr_quarantined","Typ":1},{"Name":"ocr_quarantine_reason","Typ":1}]}]`))
				return
			}
			t.Errorf("unexpected path: %s", r.URL.Path)
		}))
		defer server.Close()

		client := defra.NewClient(server.URL)
		logger := slog.Default()

		err := Initialize(context.Background(), client, logger)
		if err != nil {
			t.Errorf("Initialize() error = %v", err)
		}
	})

	t.Run("handles already exists error", func(t *testing.T) {
		var patchBody string
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/api/v0/collections" && r.Method == http.MethodPost {
				w.WriteHeader(http.StatusBadRequest)
				w.Write([]byte("collection already exists. Name: Job"))
				return
			}
			if r.URL.Path == "/api/v0/collections" && r.Method == http.MethodGet {
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`[{"Name":"Job","Fields":[{"Name":"status"}]},{"Name":"Page","Fields":[{"Name":"ocr_complete"}]}]`))
				return
			}
			if r.URL.Path == "/api/v0/collections" && r.Method == http.MethodPatch {
				body, _ := io.ReadAll(r.Body)
				patchBody = string(body)
				w.WriteHeader(http.StatusOK)
				return
			}
		}))
		defer server.Close()

		client := defra.NewClient(server.URL)
		logger := slog.Default()

		// Should succeed even though schema "already exists"
		err := Initialize(context.Background(), client, logger)
		if err != nil {
			t.Errorf("Initialize() should handle already exists, got error = %v", err)
		}
		for _, field := range []string{"status_reason", "heartbeat_at", "last_progress_at", "ocr_quarantined", "ocr_quarantine_reason"} {
			if !strings.Contains(patchBody, field) {
				t.Errorf("additive patch missing %s: %s", field, patchBody)
			}
		}
		if !strings.Contains(patchBody, `\"Typ\":1`) {
			t.Errorf("additive patch does not assign a CRDT type: %s", patchBody)
		}
	})

	t.Run("repairs additive field missing CRDT type", func(t *testing.T) {
		var patchBody string
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			switch r.Method {
			case http.MethodPost:
				w.WriteHeader(http.StatusBadRequest)
				w.Write([]byte("collection already exists"))
			case http.MethodGet:
				w.Header().Set("Content-Type", "application/json")
				w.Write([]byte(`[{"Name":"Job","Fields":[{"Name":"status_reason","Typ":1},{"Name":"heartbeat_at","Typ":1},{"Name":"last_progress_at","Typ":1}]},{"Name":"Page","Fields":[{"Name":"ocr_quarantined","Typ":0},{"Name":"ocr_quarantine_reason","Typ":0}]}]`))
			case http.MethodPatch:
				body, _ := io.ReadAll(r.Body)
				patchBody = string(body)
				w.WriteHeader(http.StatusOK)
			}
		}))
		defer server.Close()

		if err := Initialize(context.Background(), defra.NewClient(server.URL), slog.Default()); err != nil {
			t.Fatal(err)
		}
		if !strings.Contains(patchBody, `remove`) || !strings.Contains(patchBody, `/Page/Fields/1`) || !strings.Contains(patchBody, `/Page/Fields/0`) || !strings.Contains(patchBody, `\"Typ\":1`) {
			t.Fatalf("missing CRDT type repair operations: %s", patchBody)
		}
	})

	t.Run("fails on other errors", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/api/v0/collections" {
				w.WriteHeader(http.StatusBadRequest)
				w.Write([]byte("invalid schema syntax"))
				return
			}
		}))
		defer server.Close()

		client := defra.NewClient(server.URL)
		logger := slog.Default()

		err := Initialize(context.Background(), client, logger)
		if err == nil {
			t.Error("Initialize() should fail on syntax error")
		}
	})
}

func TestLowercase(t *testing.T) {
	tests := []struct {
		input string
		want  string
	}{
		{"Job", "job"},
		{"UPPERCASE", "uppercase"},
		{"already_lower", "already_lower"},
		{"MixedCase", "mixedcase"},
		{"", ""},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			got := lowercase(tt.input)
			if got != tt.want {
				t.Errorf("lowercase(%q) = %q, want %q", tt.input, got, tt.want)
			}
		})
	}
}

func TestIsAlreadyExistsError(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{"nil error", nil, false},
		{"already exists", errWithMsg("collection already exists. Name: Job"), true},
		{"already exists variant", errWithMsg("schema already exists"), true},
		{"other error", errWithMsg("invalid syntax"), false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := isAlreadyExistsError(tt.err)
			if got != tt.want {
				t.Errorf("isAlreadyExistsError() = %v, want %v", got, tt.want)
			}
		})
	}
}

// errWithMsg creates a simple error with a message
type errWithMsg string

func (e errWithMsg) Error() string { return string(e) }
