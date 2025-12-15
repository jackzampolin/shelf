package server

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// TestServer_FullLifecycle tests the complete server lifecycle including DefraDB.
// This test requires Docker to be running.
func TestServer_FullLifecycle(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	dataPath := t.TempDir()
	port := "18080" // Use non-standard port for testing

	// Clean up any existing test container first
	cleanupTestContainer(t, dataPath)

	srv, err := New(Config{
		Host:          "127.0.0.1",
		Port:          port,
		DefraDataPath: dataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: "shelf-defra-server-test",
			HostPort:      "19281", // Non-standard port
		},
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	// Start server in background
	serverErr := make(chan error, 1)
	serverCtx, serverCancel := context.WithCancel(ctx)

	go func() {
		serverErr <- srv.Start(serverCtx)
	}()

	// Wait for server to be ready
	baseURL := fmt.Sprintf("http://127.0.0.1:%s", port)
	if err := waitForServer(ctx, baseURL, 30*time.Second); err != nil {
		serverCancel()
		t.Fatalf("server did not start: %v", err)
	}

	t.Run("health_endpoint", func(t *testing.T) {
		resp, err := http.Get(baseURL + "/health")
		if err != nil {
			t.Fatalf("health check failed: %v", err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			t.Errorf("health status = %d, want %d", resp.StatusCode, http.StatusOK)
		}

		var health HealthResponse
		if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}

		if health.Status != "ok" {
			t.Errorf("health.Status = %q, want %q", health.Status, "ok")
		}
	})

	t.Run("ready_endpoint", func(t *testing.T) {
		resp, err := http.Get(baseURL + "/ready")
		if err != nil {
			t.Fatalf("ready check failed: %v", err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			t.Errorf("ready status = %d, want %d", resp.StatusCode, http.StatusOK)
		}

		var health HealthResponse
		if err := json.NewDecoder(resp.Body).Decode(&health); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}

		if health.Status != "ok" {
			t.Errorf("health.Status = %q, want %q", health.Status, "ok")
		}
		if health.Defra != "ok" {
			t.Errorf("health.Defra = %q, want %q", health.Defra, "ok")
		}
	})

	t.Run("defra_client_works", func(t *testing.T) {
		client := srv.DefraClient()
		if client == nil {
			t.Fatal("DefraClient() returned nil")
		}

		if err := client.HealthCheck(ctx); err != nil {
			t.Errorf("DefraDB health check failed: %v", err)
		}
	})

	t.Run("is_running", func(t *testing.T) {
		if !srv.IsRunning() {
			t.Error("IsRunning() = false, want true")
		}
	})

	// Shutdown server
	serverCancel()

	// Wait for server to stop
	select {
	case err := <-serverErr:
		if err != nil {
			t.Logf("server returned error (expected during shutdown): %v", err)
		}
	case <-time.After(30 * time.Second):
		t.Fatal("server did not shut down within timeout")
	}

	t.Run("not_running_after_shutdown", func(t *testing.T) {
		if srv.IsRunning() {
			t.Error("IsRunning() = true after shutdown, want false")
		}
	})

	t.Run("defra_stopped_after_shutdown", func(t *testing.T) {
		// Create a new manager to check status
		mgr, err := defra.NewDockerManager(defra.DockerConfig{
			ContainerName: "shelf-defra-server-test",
		})
		if err != nil {
			t.Fatalf("failed to create manager: %v", err)
		}
		defer mgr.Close()

		status, err := mgr.Status(ctx)
		if err != nil {
			t.Fatalf("failed to get status: %v", err)
		}

		if status == defra.StatusRunning {
			t.Error("DefraDB still running after server shutdown")
			// Clean up
			_ = mgr.Stop(ctx)
		}
	})
}

// TestServer_ContextCancellation tests that the server properly handles context cancellation.
func TestServer_ContextCancellation(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	dataPath := t.TempDir()
	port := "18081"

	cleanupTestContainer(t, dataPath)

	srv, err := New(Config{
		Host:          "127.0.0.1",
		Port:          port,
		DefraDataPath: dataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: "shelf-defra-cancel-test",
			HostPort:      "19282",
		},
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	serverErr := make(chan error, 1)
	serverCtx, serverCancel := context.WithCancel(ctx)

	go func() {
		serverErr <- srv.Start(serverCtx)
	}()

	// Wait for server to be ready
	baseURL := fmt.Sprintf("http://127.0.0.1:%s", port)
	if err := waitForServer(ctx, baseURL, 30*time.Second); err != nil {
		serverCancel()
		t.Fatalf("server did not start: %v", err)
	}

	// Cancel context immediately
	serverCancel()

	// Server should shut down gracefully
	select {
	case <-serverErr:
		// Expected
	case <-time.After(30 * time.Second):
		t.Fatal("server did not respond to context cancellation")
	}

	// Verify DefraDB is stopped
	mgr, err := defra.NewDockerManager(defra.DockerConfig{
		ContainerName: "shelf-defra-cancel-test",
	})
	if err != nil {
		t.Fatalf("failed to create manager: %v", err)
	}
	defer mgr.Close()

	status, err := mgr.Status(ctx)
	if err != nil {
		t.Fatalf("failed to get status: %v", err)
	}

	if status == defra.StatusRunning {
		t.Error("DefraDB still running after context cancellation")
		_ = mgr.Stop(ctx)
	}
}

// TestServer_DoubleStart tests that starting a running server returns an error.
func TestServer_DoubleStart(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	dataPath := t.TempDir()
	port := "18082"

	cleanupTestContainer(t, dataPath)

	srv, err := New(Config{
		Host:          "127.0.0.1",
		Port:          port,
		DefraDataPath: dataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: "shelf-defra-double-test",
			HostPort:      "19283",
		},
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	serverCtx, serverCancel := context.WithCancel(ctx)
	defer serverCancel()

	go func() {
		_ = srv.Start(serverCtx)
	}()

	// Wait for server
	baseURL := fmt.Sprintf("http://127.0.0.1:%s", port)
	if err := waitForServer(ctx, baseURL, 30*time.Second); err != nil {
		t.Fatalf("server did not start: %v", err)
	}

	// Try to start again - should fail
	err = srv.Start(ctx)
	if err == nil {
		t.Error("second Start() should return error")
	}
}

// waitForServer polls the server until it responds or timeout.
func waitForServer(ctx context.Context, baseURL string, timeout time.Duration) error {
	client := &http.Client{Timeout: 2 * time.Second}
	deadline := time.Now().Add(timeout)

	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return ctx.Err()
		default:
		}

		req, err := http.NewRequestWithContext(ctx, "GET", baseURL+"/health", nil)
		if err != nil {
			return err
		}

		resp, err := client.Do(req)
		if err == nil {
			resp.Body.Close()
			if resp.StatusCode == http.StatusOK {
				return nil
			}
		}

		time.Sleep(500 * time.Millisecond)
	}

	return fmt.Errorf("server not ready after %s", timeout)
}

// cleanupTestContainer removes any leftover test container.
func cleanupTestContainer(t *testing.T, dataPath string) {
	t.Helper()

	// Clean up various test containers
	containers := []string{
		"shelf-defra-server-test",
		"shelf-defra-cancel-test",
		"shelf-defra-double-test",
	}

	for _, name := range containers {
		mgr, err := defra.NewDockerManager(defra.DockerConfig{
			ContainerName: name,
			DataPath:      dataPath,
		})
		if err != nil {
			continue
		}
		_ = mgr.Remove(context.Background())
		mgr.Close()
	}
}
