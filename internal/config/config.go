package config

import (
	"errors"
	"fmt"
	"os"
	"regexp"
	"sync"

	"github.com/fsnotify/fsnotify"
	"github.com/spf13/viper"
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

// ProviderRegistryConfig holds resolved provider configuration for the registry.
// This is separate from providers.RegistryConfig to avoid circular imports.
type ProviderRegistryConfig struct {
	OCRProviders map[string]ResolvedOCRProvider
	LLMProviders map[string]ResolvedLLMProvider
}

// ResolvedOCRProvider has the API key resolved from environment.
type ResolvedOCRProvider struct {
	Type      string
	Model     string
	APIKey    string
	RateLimit float64
	Enabled   bool
}

// ResolvedLLMProvider has the API key resolved from environment.
type ResolvedLLMProvider struct {
	Type      string
	Model     string
	APIKey    string
	RateLimit float64
	Enabled   bool
}

// ToProviderRegistryConfig converts the config to a format suitable for providers.Registry.
// It resolves all ${ENV_VAR} references in API keys.
func (c *Config) ToProviderRegistryConfig() ProviderRegistryConfig {
	cfg := ProviderRegistryConfig{
		OCRProviders: make(map[string]ResolvedOCRProvider),
		LLMProviders: make(map[string]ResolvedLLMProvider),
	}

	for name, ocr := range c.OCRProviders {
		cfg.OCRProviders[name] = ResolvedOCRProvider{
			Type:      ocr.Type,
			Model:     ocr.Model,
			APIKey:    ResolveEnvVars(ocr.APIKey),
			RateLimit: ocr.RateLimit,
			Enabled:   ocr.Enabled,
		}
	}

	for name, llm := range c.LLMProviders {
		cfg.LLMProviders[name] = ResolvedLLMProvider{
			Type:      llm.Type,
			Model:     llm.Model,
			APIKey:    ResolveEnvVars(llm.APIKey),
			RateLimit: llm.RateLimit,
			Enabled:   llm.Enabled,
		}
	}

	return cfg
}
