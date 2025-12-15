package server

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/testutil"
)

// TestServer_ContextCancellation tests that the server properly handles context cancellation.
func TestServer_ContextCancellation(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	// Register cleanup for test containers
	_ = testutil.DockerClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	dataPath := t.TempDir()
	port := "18081"
	containerName := testutil.UniqueContainerName(t, "cancel")

	srv, err := New(Config{
		Host:          "127.0.0.1",
		Port:          port,
		DefraDataPath: dataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: containerName,
			HostPort:      "19282",
			Labels:        testutil.ContainerLabels(t),
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
		ContainerName: containerName,
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

	// Register cleanup for test containers
	_ = testutil.DockerClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	dataPath := t.TempDir()
	port := "18082"
	containerName := testutil.UniqueContainerName(t, "double")

	srv, err := New(Config{
		Host:          "127.0.0.1",
		Port:          port,
		DefraDataPath: dataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: containerName,
			HostPort:      "19283",
			Labels:        testutil.ContainerLabels(t),
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

// TestServer_CleansUpOrphanedContainer tests that the server removes any existing
// container before starting, ensuring a clean slate even after crashes.
func TestServer_CleansUpOrphanedContainer(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping integration test in short mode")
	}

	// Register cleanup for test containers
	_ = testutil.DockerClient(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	dataPath := t.TempDir()
	port := "18083"
	containerName := testutil.UniqueContainerName(t, "orphan")
	defraPort := "19284"
	labels := testutil.ContainerLabels(t)

	// First, create an "orphaned" container (simulating a crash)
	mgr, err := defra.NewDockerManager(defra.DockerConfig{
		ContainerName: containerName,
		DataPath:      dataPath,
		HostPort:      defraPort,
		Labels:        labels,
	})
	if err != nil {
		t.Fatalf("failed to create manager: %v", err)
	}

	// Start the container (this simulates an orphan from a previous crash)
	if err := mgr.Start(ctx); err != nil {
		mgr.Close()
		t.Fatalf("failed to start orphan container: %v", err)
	}

	// Verify it's running
	status, err := mgr.Status(ctx)
	if err != nil || status != defra.StatusRunning {
		mgr.Close()
		t.Fatalf("orphan container not running: status=%s, err=%v", status, err)
	}
	mgr.Close()

	// Now start the server - it should clean up the orphan and start fresh
	srv, err := New(Config{
		Host:          "127.0.0.1",
		Port:          port,
		DefraDataPath: dataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: containerName,
			HostPort:      defraPort,
			Labels:        labels,
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
		t.Fatalf("server did not start after cleaning orphan: %v", err)
	}

	// Verify server is healthy
	resp, err := http.Get(baseURL + "/ready")
	if err != nil {
		serverCancel()
		t.Fatalf("ready check failed: %v", err)
	}
	resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		serverCancel()
		t.Errorf("ready status = %d, want %d", resp.StatusCode, http.StatusOK)
	}

	// Clean shutdown
	serverCancel()
	<-serverErr
}
