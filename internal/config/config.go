package config

import (
	"errors"
	"fmt"
	"os"
	"regexp"
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"
	"gopkg.in/yaml.v2"

	"github.com/jackzampolin/shelf/internal/providers"
)

// Manager handles loading and hot-reloading configuration.
type Manager struct {
	mu        sync.RWMutex
	config    *Config
	callbacks []func(*Config)
}

// NewManager creates a new config manager and loads initial config.
func NewManager(cfgFile string) (*Manager, error) {
	cm := &Manager{
		callbacks: make([]func(*Config), 0),
	}

	if err := cm.initViper(cfgFile); err != nil {
		return nil, err
	}

	cfg, err := cm.load()
	if err != nil {
		return nil, err
	}
	cm.config = cfg

	return cm, nil
}

// initViper sets up viper with defaults and config file.
func (cm *Manager) initViper(cfgFile string) error {
	defaults := DefaultConfig()
	viper.SetDefault("ocr_providers", defaults.OCRProviders)
	viper.SetDefault("llm_providers", defaults.LLMProviders)
	viper.SetDefault("defaults", defaults.Defaults)
	viper.SetDefault("defra", defaults.Defra)

	// Environment variables with SHELF_ prefix
	viper.SetEnvPrefix("SHELF")
	viper.AutomaticEnv()

	// Config file
	if cfgFile != "" {
		viper.SetConfigFile(cfgFile)
	} else {
		viper.SetConfigName("config")
		viper.SetConfigType("yaml")
		viper.AddConfigPath(".")
		viper.AddConfigPath("$HOME/.shelf")
	}

	// Try to read config file (not required)
	if err := viper.ReadInConfig(); err != nil {
		var configFileNotFoundError viper.ConfigFileNotFoundError
		if !errors.As(err, &configFileNotFoundError) {
			return fmt.Errorf("error reading config file: %w", err)
		}
	}

	return nil
}

// load parses the current viper state into a Config struct.
func (cm *Manager) load() (*Config, error) {
	var cfg Config
	if err := viper.Unmarshal(&cfg); err != nil {
		return nil, fmt.Errorf("failed to unmarshal config: %w", err)
	}
	return &cfg, nil
}

// Get returns the current configuration (thread-safe).
func (cm *Manager) Get() *Config {
	cm.mu.RLock()
	defer cm.mu.RUnlock()
	return cm.config
}

// OnChange registers a callback for config changes.
func (cm *Manager) OnChange(fn func(*Config)) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.callbacks = append(cm.callbacks, fn)
}

// WatchConfig enables hot-reloading of configuration.
func (cm *Manager) WatchConfig() {
	viper.OnConfigChange(func(e fsnotify.Event) {
		cfg, err := cm.load()
		if err != nil {
			return
		}

		cm.mu.Lock()
		cm.config = cfg
		callbacks := make([]func(*Config), len(cm.callbacks))
		copy(callbacks, cm.callbacks)
		cm.mu.Unlock()

		for _, fn := range callbacks {
			fn(cfg)
		}
	})
	viper.WatchConfig()
}

// ResolveEnvVars expands ${ENV_VAR} references in a string.
func ResolveEnvVars(value string) string {
	if value == "" {
		return value
	}
	pattern := regexp.MustCompile(`\$\{([^}]+)\}`)
	return pattern.ReplaceAllStringFunc(value, func(match string) string {
		varName := match[2 : len(match)-1]
		return os.Getenv(varName)
	})
}

// ToProviderRegistryConfig converts the config to a format suitable for providers.Registry.
// It resolves all ${ENV_VAR} references in API keys.
func (c *Config) ToProviderRegistryConfig() providers.RegistryConfig {
	cfg := providers.RegistryConfig{
		OCRProviders: make(map[string]providers.OCRProviderConfig),
		LLMProviders: make(map[string]providers.LLMProviderConfig),
	}

	for name, ocr := range c.OCRProviders {
		cfg.OCRProviders[name] = providers.OCRProviderConfig{
			Type:      ocr.Type,
			Model:     ocr.Model,
			APIKey:    ResolveEnvVars(ocr.APIKey),
			RateLimit: ocr.RateLimit,
			Enabled:   ocr.Enabled,
		}
	}

	for name, llm := range c.LLMProviders {
		cfg.LLMProviders[name] = providers.LLMProviderConfig{
			Type:      llm.Type,
			Model:     llm.Model,
			APIKey:    ResolveEnvVars(llm.APIKey),
			RateLimit: llm.RateLimit,
			Enabled:   llm.Enabled,
		}
	}

	return cfg
}

// WriteDefault writes the default configuration to the specified path.
func WriteDefault(path string) error {
	cfg := DefaultConfig()
	data, err := yaml.Marshal(cfg)
	if err != nil {
		return fmt.Errorf("failed to marshal config: %w", err)
	}

	header := []byte(`# Shelf configuration
# API keys use ${ENV_VAR} syntax to reference environment variables
# Set these in your shell: export MISTRAL_API_KEY=xxx DEEPINFRA_API_KEY=xxx OPENROUTER_API_KEY=xxx

`)
	return os.WriteFile(path, append(header, data...), 0o644)
}
