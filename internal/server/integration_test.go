package server

import (
	"context"
	"net/http"
	"os"
	"slices"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/config"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/server/endpoints"
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

	// Wait for server to be ready, but check for early server failure
	ready := make(chan error, 1)
	go func() {
		ready <- testutil.WaitForServer(cfg.URL(), 60*time.Second)
	}()

	select {
	case err := <-serverErr:
		t.Fatalf("server failed to start: %v", err)
	case err := <-ready:
		if err != nil {
			serverCancel()
			t.Fatalf("server did not start: %v", err)
		}
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

func TestServer_ConfigHotReload(t *testing.T) {
	cfg := testutil.NewServerConfig(t)

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Minute)
	defer cancel()

	// Create initial config with one OCR provider
	initialConfig := `
ocr_providers:
  mistral:
    type: mistral-ocr
    api_key: "test-mistral-key"
    rate_limit: 6.0
    enabled: true

llm_providers:
  openrouter:
    type: openrouter
    model: "anthropic/claude-sonnet-4"
    api_key: "test-openrouter-key"
    enabled: true
`
	if err := os.WriteFile(cfg.ConfigFile, []byte(initialConfig), 0644); err != nil {
		t.Fatalf("failed to write initial config: %v", err)
	}

	// Create config manager
	cfgMgr, err := config.NewManager(cfg.ConfigFile)
	if err != nil {
		t.Fatalf("failed to create config manager: %v", err)
	}
	cfgMgr.WatchConfig()

	// Create and start server
	srv, err := New(Config{
		Host:          cfg.Host,
		Port:          cfg.Port,
		DefraDataPath: cfg.DefraDataPath,
		DefraConfig: defra.DockerConfig{
			ContainerName: cfg.DefraConfig.ContainerName,
			HostPort:      cfg.DefraConfig.HostPort,
			Labels:        cfg.DefraConfig.Labels,
		},
		ConfigManager: cfgMgr,
		Logger:        cfg.Logger,
	})
	if err != nil {
		t.Fatalf("New() error = %v", err)
	}

	serverErr := make(chan error, 1)
	serverCtx, serverCancel := context.WithCancel(ctx)
	defer serverCancel()

	go func() {
		serverErr <- srv.Start(serverCtx)
	}()

	// Wait for server to be ready
	if err := testutil.WaitForServer(cfg.URL(), 60*time.Second); err != nil {
		t.Fatalf("server did not start: %v", err)
	}

	// Check initial providers via /status endpoint
	status, err := testutil.GetStatus(cfg.URL())
	if err != nil {
		t.Fatalf("failed to get initial status: %v", err)
	}

	t.Logf("Initial providers: OCR=%v, LLM=%v", status.Providers.OCR, status.Providers.LLM)

	if !slices.Contains(status.Providers.OCR, "mistral") {
		t.Errorf("expected mistral in OCR providers, got %v", status.Providers.OCR)
	}
	if !slices.Contains(status.Providers.LLM, "openrouter") {
		t.Errorf("expected openrouter in LLM providers, got %v", status.Providers.LLM)
	}

	// Update config to add DeepInfra OCR provider
	updatedConfig := `
ocr_providers:
  mistral:
    type: mistral-ocr
    api_key: "test-mistral-key"
    rate_limit: 6.0
    enabled: true
  deepinfra:
    type: deepinfra
    model: "ds-paddleocr-vl"
    api_key: "test-deepinfra-key"
    rate_limit: 10.0
    enabled: true

llm_providers:
  openrouter:
    type: openrouter
    model: "anthropic/claude-sonnet-4"
    api_key: "test-openrouter-key"
    enabled: true
`
	if err := os.WriteFile(cfg.ConfigFile, []byte(updatedConfig), 0644); err != nil {
		t.Fatalf("failed to write updated config: %v", err)
	}

	// Wait for hot reload to pick up changes
	time.Sleep(500 * time.Millisecond)

	// Poll for DeepInfra to appear
	deadline := time.Now().Add(5 * time.Second)
	var foundDeepInfra bool
	for time.Now().Before(deadline) {
		status, err = testutil.GetStatus(cfg.URL())
		if err != nil {
			t.Fatalf("failed to get status after update: %v", err)
		}
		if slices.Contains(status.Providers.OCR, "deepinfra") {
			foundDeepInfra = true
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	if !foundDeepInfra {
		t.Errorf("expected deepinfra to appear after hot reload, got OCR=%v", status.Providers.OCR)
	}

	t.Logf("After adding DeepInfra: OCR=%v, LLM=%v", status.Providers.OCR, status.Providers.LLM)

	// Now remove Mistral provider
	removedConfig := `
ocr_providers:
  deepinfra:
    type: deepinfra
    model: "ds-paddleocr-vl"
    api_key: "test-deepinfra-key"
    rate_limit: 10.0
    enabled: true

llm_providers:
  openrouter:
    type: openrouter
    model: "anthropic/claude-sonnet-4"
    api_key: "test-openrouter-key"
    enabled: true
`
	if err := os.WriteFile(cfg.ConfigFile, []byte(removedConfig), 0644); err != nil {
		t.Fatalf("failed to write config with removed provider: %v", err)
	}

	// Wait for hot reload
	time.Sleep(500 * time.Millisecond)

	// Poll for Mistral to disappear
	deadline = time.Now().Add(5 * time.Second)
	var mistralRemoved bool
	for time.Now().Before(deadline) {
		status, err = testutil.GetStatus(cfg.URL())
		if err != nil {
			t.Fatalf("failed to get status after removal: %v", err)
		}
		if !slices.Contains(status.Providers.OCR, "mistral") {
			mistralRemoved = true
			break
		}
		time.Sleep(200 * time.Millisecond)
	}

	if !mistralRemoved {
		t.Errorf("expected mistral to be removed after hot reload, got OCR=%v", status.Providers.OCR)
	}

	// Verify DeepInfra is still there
	if !slices.Contains(status.Providers.OCR, "deepinfra") {
		t.Errorf("expected deepinfra to remain, got OCR=%v", status.Providers.OCR)
	}

	t.Logf("After removing Mistral: OCR=%v, LLM=%v", status.Providers.OCR, status.Providers.LLM)

	// Clean shutdown
	serverCancel()
	select {
	case <-serverErr:
		// Expected
	case <-time.After(30 * time.Second):
		t.Fatal("server did not shut down")
	}
}

func TestCLI_StatusEndpoint(t *testing.T) {
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
	defer serverCancel()

	go func() {
		serverErr <- srv.Start(serverCtx)
	}()

	// Wait for server to be ready
	if err := testutil.WaitForServer(cfg.URL(), 60*time.Second); err != nil {
		t.Fatalf("server did not start: %v", err)
	}

	// Test CLI commands via endpoint's Command method
	// These tests verify the CLI -> HTTP -> Server round-trip works
	t.Run("status_cli_command", func(t *testing.T) {
		ep := &endpoints.StatusEndpoint{}
		cmd := ep.Command(func() string { return cfg.URL() })

		if err := cmd.Execute(); err != nil {
			t.Fatalf("status command failed: %v", err)
		}
		// Command succeeded - round-trip worked
	})

	t.Run("health_cli_command", func(t *testing.T) {
		ep := &endpoints.HealthEndpoint{}
		cmd := ep.Command(func() string { return cfg.URL() })

		if err := cmd.Execute(); err != nil {
			t.Fatalf("health command failed: %v", err)
		}
	})

	t.Run("ready_cli_command", func(t *testing.T) {
		ep := &endpoints.ReadyEndpoint{}
		cmd := ep.Command(func() string { return cfg.URL() })

		if err := cmd.Execute(); err != nil {
			t.Fatalf("ready command failed: %v", err)
		}
	})

	// Clean shutdown
	serverCancel()
	select {
	case <-serverErr:
		// Expected
	case <-time.After(30 * time.Second):
		t.Fatal("server did not shut down")
	}
}
