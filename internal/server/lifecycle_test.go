package server

import (
	"context"
	"encoding/json"
	"net/http"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/testutil"
)

func TestServer_FullLifecycle(t *testing.T) {
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

	// Start server in background
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

	t.Run("health_endpoint", func(t *testing.T) {
		resp, err := http.Get(cfg.URL() + "/health")
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
		resp, err := http.Get(cfg.URL() + "/ready")
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

	t.Run("status_endpoint", func(t *testing.T) {
		resp, err := http.Get(cfg.URL() + "/status")
		if err != nil {
			t.Fatalf("status check failed: %v", err)
		}
		defer resp.Body.Close()

		if resp.StatusCode != http.StatusOK {
			t.Errorf("status code = %d, want %d", resp.StatusCode, http.StatusOK)
		}

		var status StatusResponse
		if err := json.NewDecoder(resp.Body).Decode(&status); err != nil {
			t.Fatalf("failed to decode response: %v", err)
		}

		if status.Server != "running" {
			t.Errorf("status.Server = %q, want %q", status.Server, "running")
		}
		if status.Defra.Health != "healthy" {
			t.Errorf("status.Defra.Health = %q, want %q", status.Defra.Health, "healthy")
		}
		if status.Defra.Container != "running" {
			t.Errorf("status.Defra.Container = %q, want %q", status.Defra.Container, "running")
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
			t.Error("DefraDB still running after server shutdown")
			_ = mgr.Stop(ctx)
		}
	})
}
