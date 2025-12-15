package schema

import (
	"context"
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
			if r.URL.Path == "/api/v0/schema" {
				w.WriteHeader(http.StatusOK)
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
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/api/v0/schema" {
				w.WriteHeader(http.StatusBadRequest)
				w.Write([]byte("collection already exists. Name: Job"))
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
	})

	t.Run("fails on other errors", func(t *testing.T) {
		server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path == "/api/v0/schema" {
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
