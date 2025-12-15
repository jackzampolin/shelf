package config

import (
	"os"
	"path/filepath"
	"testing"
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
