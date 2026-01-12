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

	if len(cfg.OCRProviders) == 0 {
		t.Error("expected default OCR providers")
	}
	mistral, ok := cfg.OCRProviders["mistral"]
	if !ok {
		t.Error("expected mistral provider")
	}
	if mistral.APIKey != "${MISTRAL_API_KEY}" {
		t.Error("expected mistral API key placeholder")
	}

	if len(cfg.LLMProviders) == 0 {
		t.Error("expected default LLM providers")
	}
	openrouter, ok := cfg.LLMProviders["openrouter"]
	if !ok {
		t.Error("expected openrouter provider")
	}
	if openrouter.APIKey != "${OPENROUTER_API_KEY}" {
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


func TestNewManager(t *testing.T) {
	t.Run("loads from config file", func(t *testing.T) {
		tmpDir := t.TempDir()
		configFile := filepath.Join(tmpDir, "config.yaml")

		configContent := `
ocr_providers:
  test_ocr:
    type: "mistral-ocr"
    api_key: "test-api-key"
    enabled: true
`
		if err := os.WriteFile(configFile, []byte(configContent), 0644); err != nil {
			t.Fatalf("failed to write config file: %v", err)
		}

		mgr, err := NewManager(configFile)
		if err != nil {
			t.Fatalf("failed to create manager: %v", err)
		}

		cfg := mgr.Get()
		ocr, ok := cfg.OCRProviders["test_ocr"]
		if !ok {
			t.Fatal("expected test_ocr provider")
		}
		if ocr.APIKey != "test-api-key" {
			t.Errorf("expected test-api-key, got %s", ocr.APIKey)
		}
	})
}

func TestManager_OnChange(t *testing.T) {
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.yaml")

	configContent := `
ocr_providers:
  test:
    type: "mistral-ocr"
    api_key: "initial_value"
    enabled: true
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
ocr_providers:
  test:
    type: "mistral-ocr"
    api_key: "value"
    enabled: true
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
ocr_providers:
  test:
    type: "mistral-ocr"
    api_key: "value"
    enabled: true
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
				_ = cfg.OCRProviders["test"]
			}
			done <- struct{}{}
		}()
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		<-done
	}
}

func TestConfig_ToProviderRegistryConfig(t *testing.T) {
	os.Setenv("TEST_MISTRAL_KEY", "mistral-secret")
	os.Setenv("TEST_OPENROUTER_KEY", "openrouter-secret")
	defer os.Unsetenv("TEST_MISTRAL_KEY")
	defer os.Unsetenv("TEST_OPENROUTER_KEY")

	cfg := &Config{
		OCRProviders: map[string]OCRProviderCfg{
			"mistral": {
				Type:      "mistral-ocr",
				APIKey:    "${TEST_MISTRAL_KEY}",
				RateLimit: 6.0,
				Enabled:   true,
			},
			"deepinfra": {
				Type:      "deepinfra",
				Model:     "ds-paddleocr-vl",
				APIKey:    "literal-deepinfra-key",
				RateLimit: 10.0,
				Enabled:   true,
			},
			"disabled": {
				Type:    "mistral-ocr",
				APIKey:  "${TEST_MISTRAL_KEY}",
				Enabled: false,
			},
		},
		LLMProviders: map[string]LLMProviderCfg{
			"openrouter": {
				Type:      "openrouter",
				Model:     "anthropic/claude-sonnet-4",
				APIKey:    "${TEST_OPENROUTER_KEY}",
				RateLimit: 60.0,
				Enabled:   true,
			},
		},
	}

	result := cfg.ToProviderRegistryConfig()

	t.Run("resolves OCR provider API keys from env", func(t *testing.T) {
		mistral, ok := result.OCRProviders["mistral"]
		if !ok {
			t.Fatal("mistral provider not found")
		}
		if mistral.APIKey != "mistral-secret" {
			t.Errorf("expected mistral-secret, got %s", mistral.APIKey)
		}
		if mistral.Type != "mistral-ocr" {
			t.Errorf("expected type mistral-ocr, got %s", mistral.Type)
		}
	})

	t.Run("keeps literal API keys", func(t *testing.T) {
		deepinfra, ok := result.OCRProviders["deepinfra"]
		if !ok {
			t.Fatal("deepinfra provider not found")
		}
		if deepinfra.APIKey != "literal-deepinfra-key" {
			t.Errorf("expected literal-deepinfra-key, got %s", deepinfra.APIKey)
		}
		if deepinfra.Model != "ds-paddleocr-vl" {
			t.Errorf("expected model ds-paddleocr-vl, got %s", deepinfra.Model)
		}
	})

	t.Run("includes disabled providers", func(t *testing.T) {
		disabled, ok := result.OCRProviders["disabled"]
		if !ok {
			t.Fatal("disabled provider not found")
		}
		if disabled.Enabled {
			t.Error("expected Enabled=false")
		}
	})

	t.Run("resolves LLM provider API keys", func(t *testing.T) {
		openrouter, ok := result.LLMProviders["openrouter"]
		if !ok {
			t.Fatal("openrouter provider not found")
		}
		if openrouter.APIKey != "openrouter-secret" {
			t.Errorf("expected openrouter-secret, got %s", openrouter.APIKey)
		}
		if openrouter.Model != "anthropic/claude-sonnet-4" {
			t.Errorf("expected model anthropic/claude-sonnet-4, got %s", openrouter.Model)
		}
	})
}

func TestManager_WatchConfig(t *testing.T) {
	tmpDir := t.TempDir()
	configFile := filepath.Join(tmpDir, "config.yaml")

	configContent := `
ocr_providers:
  test:
    type: "mistral-ocr"
    api_key: "initial_value"
    enabled: true
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
	if cfg.OCRProviders["test"].APIKey != "initial_value" {
		t.Errorf("initial value mismatch: expected initial_value, got %s", cfg.OCRProviders["test"].APIKey)
	}

	// Track callback invocations
	var callbackCount atomic.Int32
	var lastValue atomic.Value

	mgr.OnChange(func(cfg *Config) {
		callbackCount.Add(1)
		lastValue.Store(cfg.OCRProviders["test"].APIKey)
	})

	// Start watching
	mgr.WatchConfig()

	// Give fsnotify time to set up the watcher
	time.Sleep(100 * time.Millisecond)

	// Update the config file
	newContent := `
ocr_providers:
  test:
    type: "mistral-ocr"
    api_key: "updated_value"
    enabled: true
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
	if newCfg.OCRProviders["test"].APIKey != "updated_value" {
		t.Errorf("config not updated: expected updated_value, got %s", newCfg.OCRProviders["test"].APIKey)
	}

	// Verify callback received the updated value
	if v := lastValue.Load(); v != "updated_value" {
		t.Errorf("callback received wrong value: expected updated_value, got %v", v)
	}
}
