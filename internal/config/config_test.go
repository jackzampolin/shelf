package config

import (
	"os"
	"path/filepath"
	"sync/atomic"
	"testing"
	"time"
)

func TestDefaultConfig(t *testing.T) {
	cfg := DefaultConfig()

	if len(cfg.APIKeys) == 0 {
		t.Error("expected default API keys")
	}
	if cfg.APIKeys["openrouter"] != "${OPENROUTER_API_KEY}" {
		t.Error("expected openrouter API key placeholder")
	}
}

func TestResolveEnvVars(t *testing.T) {
	t.Run("resolves environment variable", func(t *testing.T) {
		os.Setenv("TEST_API_KEY", "secret123")
		defer os.Unsetenv("TEST_API_KEY")

		result := ResolveEnvVars("${TEST_API_KEY}")
		if result != "secret123" {
			t.Errorf("expected secret123, got %s", result)
		}
	})

	t.Run("returns empty for missing env var", func(t *testing.T) {
		result := ResolveEnvVars("${DEFINITELY_NOT_SET_12345}")
		if result != "" {
			t.Errorf("expected empty string, got %s", result)
		}
	})

	t.Run("leaves literal values unchanged", func(t *testing.T) {
		result := ResolveEnvVars("literal-value")
		if result != "literal-value" {
			t.Errorf("expected literal-value, got %s", result)
		}
	})
}

func TestConfig_ResolveAPIKey(t *testing.T) {
	os.Setenv("TEST_OPENROUTER_KEY", "or-key-123")
	defer os.Unsetenv("TEST_OPENROUTER_KEY")

	cfg := &Config{
		APIKeys: map[string]string{
			"openrouter": "${TEST_OPENROUTER_KEY}",
			"literal":    "direct-key",
		},
	}

	t.Run("resolves env var reference", func(t *testing.T) {
		result := cfg.ResolveAPIKey("openrouter")
		if result != "or-key-123" {
			t.Errorf("expected or-key-123, got %s", result)
		}
	})

	t.Run("returns literal value", func(t *testing.T) {
		result := cfg.ResolveAPIKey("literal")
		if result != "direct-key" {
			t.Errorf("expected direct-key, got %s", result)
		}
	})
}

func TestNewManager(t *testing.T) {
	t.Run("loads from config file", func(t *testing.T) {
		tmpDir := t.TempDir()
		configFile := filepath.Join(tmpDir, "config.yaml")

		configContent := `
api_keys:
  test_key: "test_value"
`
		if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
			t.Fatalf("failed to write config file: %v", err)
		}

		mgr, err := NewManager(configFile)
		if err != nil {
			t.Fatalf("failed to create manager: %v", err)
		}

		cfg := mgr.Get()
		if cfg.APIKeys["test_key"] != "test_value" {
			t.Errorf("expected test_value, got %s", cfg.APIKeys["test_key"])
		}
	})
}

func TestManager_OnChange(t *testing.T) {
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.yaml")

	configContent := `
api_keys:
  test_key: "initial_value"
`
	if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	mgr, err := NewManager(configFile)
	if err != nil {
		t.Fatalf("failed to create manager: %v", err)
	}

	// Track callback invocations
	callbackCount := 0
	var lastConfig *Config

	mgr.OnChange(func(cfg *Config) {
		callbackCount++
		lastConfig = cfg
	})

	// Verify callback is registered
	mgr.mu.RLock()
	if len(mgr.callbacks) != 1 {
		t.Errorf("expected 1 callback, got %d", len(mgr.callbacks))
	}
	mgr.mu.RUnlock()

	// Note: Actually triggering the callback requires WatchConfig + file change
	// which is tested in TestManager_WatchConfig
	_ = lastConfig
	_ = callbackCount
}

func TestManager_OnChange_Multiple(t *testing.T) {
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.yaml")

	configContent := `
api_keys:
  key: "value"
`
	if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	mgr, err := NewManager(configFile)
	if err != nil {
		t.Fatalf("failed to create manager: %v", err)
	}

	// Register multiple callbacks
	mgr.OnChange(func(cfg *Config) {})
	mgr.OnChange(func(cfg *Config) {})
	mgr.OnChange(func(cfg *Config) {})

	mgr.mu.RLock()
	if len(mgr.callbacks) != 3 {
		t.Errorf("expected 3 callbacks, got %d", len(mgr.callbacks))
	}
	mgr.mu.RUnlock()
}

func TestManager_Get_ThreadSafe(t *testing.T) {
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.yaml")

	configContent := `
api_keys:
  key: "value"
`
	if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	mgr, err := NewManager(configFile)
	if err != nil {
		t.Fatalf("failed to create manager: %v", err)
	}

	// Call Get concurrently to verify no race conditions
	done := make(chan struct{})
	for i := 0; i < 10; i++ {
		go func() {
			for j := 0; j < 100; j++ {
				cfg := mgr.Get()
				_ = cfg.APIKeys["key"]
			}
			done <- struct{}{}
		}()
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		<-done
	}
}

func TestManager_WatchConfig(t *testing.T) {
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.yaml")

	configContent := `
api_keys:
  test_key: "initial_value"
`
	if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
		t.Fatalf("failed to write config file: %v", err)
	}

	mgr, err := NewManager(configFile)
	if err != nil {
		t.Fatalf("failed to create manager: %v", err)
	}

	// Verify initial value
	cfg := mgr.Get()
	if cfg.APIKeys["test_key"] != "initial_value" {
		t.Errorf("initial value mismatch: expected initial_value, got %s", cfg.APIKeys["test_key"])
	}

	// Track callback invocations
	var callbackCount atomic.Int32
	var lastValue atomic.Value

	mgr.OnChange(func(cfg *Config) {
		callbackCount.Add(1)
		lastValue.Store(cfg.APIKeys["test_key"])
	})

	// Start watching
	mgr.WatchConfig()

	// Give fsnotify time to set up the watcher
	time.Sleep(100 * time.Millisecond)

	// Update the config file
	newContent := `
api_keys:
  test_key: "updated_value"
`
	if err := os.WriteFile(configFile, []byte(newContent), 0644); err != nil {
		t.Fatalf("failed to write updated config file: %v", err)
	}

	// Wait for the watcher to detect the change (fsnotify is async)
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if callbackCount.Load() > 0 {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	if callbackCount.Load() == 0 {
		t.Error("callback was not invoked after config file change")
	}

	// Verify the config was updated
	newCfg := mgr.Get()
	if newCfg.APIKeys["test_key"] != "updated_value" {
		t.Errorf("config not updated: expected updated_value, got %s", newCfg.APIKeys["test_key"])
	}

	// Verify callback received the updated value
	if v := lastValue.Load(); v != "updated_value" {
		t.Errorf("callback received wrong value: expected updated_value, got %v", v)
	}
}
