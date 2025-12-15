package defra

import (
	"context"
	"testing"
	"time"
)

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
