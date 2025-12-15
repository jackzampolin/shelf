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
	viper.SetDefault("api_keys", defaults.APIKeys)

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

// ResolveAPIKey resolves an API key, expanding ${ENV_VAR} references.
func (c *Config) ResolveAPIKey(name string) string {
	return ResolveEnvVars(c.GetAPIKey(name))
}
