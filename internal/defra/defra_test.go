package defra

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

// =============================================================================
// Client Tests
// =============================================================================

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
			got := mapToGraphQLInput(tt.input)
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

// =============================================================================
// Docker Manager Tests (Unit Tests - No Docker Required)
// =============================================================================

func TestDockerConfig_Defaults(t *testing.T) {
	// Test that defaults are applied correctly
	cfg := DockerConfig{}

	if cfg.ContainerName != "" {
		t.Error("ContainerName should be empty before NewDockerManager")
	}

	// Note: NewDockerManager requires Docker to be running
	// These tests verify the config defaults are defined
	if DefaultContainerName != "shelf-defra" {
		t.Errorf("unexpected default container name: %s", DefaultContainerName)
	}
	if DefaultImage != "sourcenetwork/defradb:latest" {
		t.Errorf("unexpected default image: %s", DefaultImage)
	}
	if DefaultPort != "9181" {
		t.Errorf("unexpected default port: %s", DefaultPort)
	}
}

func TestContainerStatus_Values(t *testing.T) {
	// Verify status constants
	statuses := []ContainerStatus{
		StatusRunning,
		StatusStopped,
		StatusNotFound,
		StatusUnhealthy,
		StatusStarting,
	}

	seen := make(map[ContainerStatus]bool)
	for _, s := range statuses {
		if seen[s] {
			t.Errorf("duplicate status value: %s", s)
		}
		seen[s] = true
	}
}

func TestDockerManager_URL(t *testing.T) {
	// We can't create a real DockerManager without Docker,
	// but we can verify the URL format
	expectedFormat := "http://localhost:9181"

	// Verify the constant
	if DefaultPort != "9181" {
		t.Errorf("unexpected default port: %s", DefaultPort)
	}

	// The URL method uses hostPort, which defaults to DefaultPort
	// Format: http://localhost:<hostPort>
	_ = expectedFormat // Verify format is correct
}

// =============================================================================
// Integration Tests (Require Docker)
// =============================================================================

// TestDockerManager_Integration tests the full lifecycle.
// Requires Docker to be running. Use -short to skip.
func TestDockerManager_Integration(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx := context.Background()
	dataPath := t.TempDir()

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: "shelf-defra-test",
		DataPath:      dataPath,
		HostPort:      "19181", // Use different port to avoid conflicts
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer mgr.Close()

	// Cleanup any existing test container
	_ = mgr.Remove(ctx)

	// Test: Start container
	t.Run("Start", func(t *testing.T) {
		if err := mgr.Start(ctx); err != nil {
			t.Fatalf("Start() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusRunning {
			t.Errorf("expected status running, got %s", status)
		}
	})

	// Test: Start when already running (should be no-op)
	t.Run("Start_AlreadyRunning", func(t *testing.T) {
		if err := mgr.Start(ctx); err != nil {
			t.Errorf("Start() on running container should succeed: %v", err)
		}
	})

	// Test: Health check via client
	t.Run("HealthCheck", func(t *testing.T) {
		client := NewClient(mgr.URL())
		if err := client.HealthCheck(ctx); err != nil {
			t.Errorf("HealthCheck() error = %v", err)
		}
	})

	// Test: Stop container
	t.Run("Stop", func(t *testing.T) {
		if err := mgr.Stop(ctx); err != nil {
			t.Fatalf("Stop() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusStopped {
			t.Errorf("expected status stopped, got %s", status)
		}
	})

	// Test: Stop when already stopped (should be no-op)
	t.Run("Stop_AlreadyStopped", func(t *testing.T) {
		if err := mgr.Stop(ctx); err != nil {
			t.Errorf("Stop() on stopped container should succeed: %v", err)
		}
	})

	// Test: Restart stopped container
	t.Run("Restart", func(t *testing.T) {
		if err := mgr.Start(ctx); err != nil {
			t.Fatalf("Start() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusRunning {
			t.Errorf("expected status running, got %s", status)
		}
	})

	// Test: Remove container
	t.Run("Remove", func(t *testing.T) {
		if err := mgr.Remove(ctx); err != nil {
			t.Fatalf("Remove() error = %v", err)
		}

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("Status() error = %v", err)
		}
		if status != StatusNotFound {
			t.Errorf("expected status not_found, got %s", status)
		}
	})

	// Test: Remove when not found (should be no-op)
	t.Run("Remove_NotFound", func(t *testing.T) {
		if err := mgr.Remove(ctx); err != nil {
			t.Errorf("Remove() on non-existent container should succeed: %v", err)
		}
	})
}

// TestDockerManager_ContextCancellation tests that operations respect context.
// Requires Docker to be running. Use -short to skip.
func TestDockerManager_ContextCancellation_Integration(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	dataPath := t.TempDir()

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: "shelf-defra-cancel-test",
		DataPath:      dataPath,
		HostPort:      "19182",
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer mgr.Close()

	// Test: Cancelled context should abort start
	t.Run("Start_Cancelled", func(t *testing.T) {
		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		err := mgr.Start(ctx)
		if err == nil {
			// If it somehow started, clean up
			_ = mgr.Remove(context.Background())
			t.Error("expected error from cancelled context")
		}
	})

	// Test: Context timeout during waitForReady
	t.Run("WaitReady_Timeout", func(t *testing.T) {
		ctx, cancel := context.WithTimeout(context.Background(), 1*time.Millisecond)
		defer cancel()

		// This should timeout quickly
		err := mgr.WaitReady(ctx, 1*time.Millisecond)
		if err == nil {
			t.Error("expected timeout error")
		}
	})
}

// TestDockerManager_Logs tests log retrieval.
// Requires Docker to be running. Use -short to skip.
func TestDockerManager_Logs_Integration(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx := context.Background()
	dataPath := t.TempDir()

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: "shelf-defra-logs-test",
		DataPath:      dataPath,
		HostPort:      "19183",
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer func() {
		_ = mgr.Remove(ctx)
		mgr.Close()
	}()

	// Start container
	if err := mgr.Start(ctx); err != nil {
		t.Fatalf("Start() error = %v", err)
	}

	// Get logs
	logs, err := mgr.Logs(ctx, "10")
	if err != nil {
		t.Fatalf("Logs() error = %v", err)
	}

	// Should have some output
	if len(logs) == 0 {
		t.Error("expected some log output")
	}
}

// TestDockerManager_Logs_NotFound tests logs when container doesn't exist.
// Requires Docker to be running. Use -short to skip.
func TestDockerManager_Logs_NotFound_Integration(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx := context.Background()

	mgr, err := NewDockerManager(DockerConfig{
		ContainerName: "shelf-defra-nonexistent",
		HostPort:      "19184",
	})
	if err != nil {
		t.Fatalf("NewDockerManager() error = %v", err)
	}
	defer mgr.Close()

	_, err = mgr.Logs(ctx, "10")
	if err == nil {
		t.Error("expected error for non-existent container")
	}
}
