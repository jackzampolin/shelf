package defra

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestClient_HealthCheck(t *testing.T) {
	tests := []struct {
		name       string
		statusCode int
		wantErr    bool
	}{
		{"healthy", http.StatusOK, false},
		{"unhealthy_500", http.StatusInternalServerError, true},
		{"unhealthy_503", http.StatusServiceUnavailable, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/health-check" {
					t.Errorf("unexpected path: %s", r.URL.Path)
				}
				w.WriteHeader(tt.statusCode)
			}))
			defer server.Close()

			client := NewClient(server.URL)
			err := client.HealthCheck(context.Background())

			if (err != nil) != tt.wantErr {
				t.Errorf("HealthCheck() error = %v, wantErr %v", err, tt.wantErr)
			}
		})
	}
}

func TestClient_HealthCheck_ContextCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(100 * time.Millisecond)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewClient(server.URL)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // Cancel immediately

	err := client.HealthCheck(ctx)
	if err == nil {
		t.Error("expected error from cancelled context")
	}
}

func TestClient_Execute(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v0/graphql" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		if r.Method != "POST" {
			t.Errorf("unexpected method: %s", r.Method)
		}
		if ct := r.Header.Get("Content-Type"); ct != "application/json" {
			t.Errorf("unexpected content-type: %s", ct)
		}

		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data": {"Book": [{"_docID": "abc123", "title": "Test"}]}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	resp, err := client.Execute(context.Background(), `{ Book { _docID title } }`, nil)

	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}
	if resp.Error() != "" {
		t.Errorf("unexpected GraphQL error: %s", resp.Error())
	}
	if resp.Data == nil {
		t.Error("expected data in response")
	}
}

func TestClient_Execute_WithVariables(t *testing.T) {
	var receivedBody []byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedBody = make([]byte, r.ContentLength)
		r.Body.Read(receivedBody)

		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data": {"Book": []}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	vars := map[string]any{"id": "test-id", "limit": 10}
	_, err := client.Execute(context.Background(), `query($id: String!) { Book(filter: {_docID: $id}) { title } }`, vars)

	if err != nil {
		t.Fatalf("Execute() error = %v", err)
	}

	// Verify variables were sent
	if len(receivedBody) == 0 {
		t.Error("expected request body")
	}
}

func TestClient_Execute_GraphQLError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"errors": [{"message": "field not found"}]}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	resp, err := client.Execute(context.Background(), `{ Invalid }`, nil)

	if err != nil {
		t.Fatalf("Execute() returned transport error: %v", err)
	}
	if resp.Error() == "" {
		t.Error("expected GraphQL error in response")
	}
	if resp.Error() != "field not found" {
		t.Errorf("unexpected error message: %s", resp.Error())
	}
}

func TestClient_Execute_ContextCancellation(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		time.Sleep(100 * time.Millisecond)
		w.Write([]byte(`{"data": {}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()

	_, err := client.Execute(ctx, `{ Book { title } }`, nil)
	if err == nil {
		t.Error("expected error from cancelled context")
	}
}

func TestClient_AddSchema(t *testing.T) {
	var receivedSchema string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v0/schema" {
			t.Errorf("unexpected path: %s", r.URL.Path)
		}
		if r.Method != "POST" {
			t.Errorf("unexpected method: %s", r.Method)
		}
		if ct := r.Header.Get("Content-Type"); ct != "text/plain" {
			t.Errorf("unexpected content-type: %s", ct)
		}

		body := make([]byte, r.ContentLength)
		r.Body.Read(body)
		receivedSchema = string(body)

		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	client := NewClient(server.URL)
	schema := `type Book { title: String }`
	err := client.AddSchema(context.Background(), schema)

	if err != nil {
		t.Fatalf("AddSchema() error = %v", err)
	}
	if receivedSchema != schema {
		t.Errorf("schema mismatch: got %q, want %q", receivedSchema, schema)
	}
}

func TestClient_AddSchema_Error(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusBadRequest)
		w.Write([]byte("invalid schema syntax"))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	err := client.AddSchema(context.Background(), `invalid {`)

	if err == nil {
		t.Error("expected error for invalid schema")
	}
}

func TestClient_Create(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data": {"create_Book": [{"_docID": "bae-abc123"}]}}`))
	}))
	defer server.Close()

	client := NewClient(server.URL)
	docID, err := client.Create(context.Background(), "Book", map[string]any{
		"title":  "Test Book",
		"author": "Test Author",
	})

	if err != nil {
		t.Fatalf("Create() error = %v", err)
	}
	if docID != "bae-abc123" {
		t.Errorf("unexpected docID: %s", docID)
	}
}

func TestClient_URLNormalization(t *testing.T) {
	// URL with trailing slash should be normalized
	client := NewClient("http://localhost:9181/")
	if client.url != "http://localhost:9181" {
		t.Errorf("URL not normalized: %s", client.url)
	}

	// URL without trailing slash should stay the same
	client2 := NewClient("http://localhost:9181")
	if client2.url != "http://localhost:9181" {
		t.Errorf("URL changed unexpectedly: %s", client2.url)
	}
}

func TestMapToGraphQLInput(t *testing.T) {
	tests := []struct {
		name  string
		input map[string]any
		want  []string // Possible outputs (map iteration order is random)
	}{
		{
			name:  "string value",
			input: map[string]any{"title": "Test"},
			want:  []string{`{title: "Test"}`},
		},
		{
			name:  "int value",
			input: map[string]any{"count": 42},
			want:  []string{`{count: 42}`},
		},
		{
			name:  "bool value",
			input: map[string]any{"active": true},
			want:  []string{`{active: true}`},
		},
		{
			name:  "empty map",
			input: map[string]any{},
			want:  []string{`{}`},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got, err := mapToGraphQLInput(tt.input)
			if err != nil {
				t.Fatalf("mapToGraphQLInput() error = %v", err)
			}
			found := false
			for _, want := range tt.want {
				if got == want {
					found = true
					break
				}
			}
			if !found {
				t.Errorf("mapToGraphQLInput() = %v, want one of %v", got, tt.want)
			}
		})
	}
}
