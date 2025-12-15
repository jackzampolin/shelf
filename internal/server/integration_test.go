package server

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/testutil"
)

func TestServer_ContextCancellation(t *testing.T) {
	cfg := testutil.NewServerConfig(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	srv, err := New(Config{
		Host:          cfg.Host,
		Port:          cfg.Port,
		DefraDataPath: cfg.DefraDataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: cfg.DefraConfig.ContainerName,
			HostPort:      cfg.DefraConfig.HostPort,
			Labels:        cfg.DefraConfig.Labels,
		},
		Logger: cfg.Logger,
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
	if err := testutil.WaitForServer(cfg.URL(), 60*time.Second); err != nil {
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
		ContainerName: cfg.DefraConfig.ContainerName,
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

func TestServer_DoubleStart(t *testing.T) {
	cfg := testutil.NewServerConfig(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	srv, err := New(Config{
		Host:          cfg.Host,
		Port:          cfg.Port,
		DefraDataPath: cfg.DefraDataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: cfg.DefraConfig.ContainerName,
			HostPort:      cfg.DefraConfig.HostPort,
			Labels:        cfg.DefraConfig.Labels,
		},
		Logger: cfg.Logger,
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
	if err := testutil.WaitForServer(cfg.URL(), 60*time.Second); err != nil {
		t.Fatalf("server did not start: %v", err)
	}

	// Try to start again - should fail
	err = srv.Start(ctx)
	if err == nil {
		t.Error("second Start() should return error")
	}
}

func TestServer_CleansUpOrphanedContainer(t *testing.T) {
	cfg := testutil.NewServerConfig(t)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Minute)
	defer cancel()

	// First, create an "orphaned" container (simulating a crash)
	mgr, err := defra.NewDockerManager(defra.DockerConfig{
		ContainerName: cfg.DefraConfig.ContainerName,
		DataPath:      cfg.DefraDataPath,
		HostPort:      cfg.DefraConfig.HostPort,
		Labels:        cfg.DefraConfig.Labels,
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
		Host:          cfg.Host,
		Port:          cfg.Port,
		DefraDataPath: cfg.DefraDataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: cfg.DefraConfig.ContainerName,
			HostPort:      cfg.DefraConfig.HostPort,
			Labels:        cfg.DefraConfig.Labels,
		},
		Logger: cfg.Logger,
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
	if err := testutil.WaitForServer(cfg.URL(), 60*time.Second); err != nil {
		serverCancel()
		t.Fatalf("server did not start after cleaning orphan: %v", err)
	}

	// Verify server is healthy
	resp, err := http.Get(cfg.URL() + "/ready")
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
