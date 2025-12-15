package config

// Config holds shelf configuration.
// Stored at: {storage_root}/config.yaml
type Config struct {
	APIKeys map[string]string `mapstructure:"api_keys" yaml:"api_keys"`
}

// DefaultConfig returns configuration with sensible defaults.
func DefaultConfig() *Config {
	return &Config{
		APIKeys: map[string]string{
			"openrouter": "${OPENROUTER_API_KEY}",
			"mistral":    "${MISTRAL_API_KEY}",
			"deepinfra":  "${DEEPINFRA_API_KEY}",
			"datalab":    "${DATALAB_API_KEY}",
			"deepseek":   "${DEEPSEEK_API_KEY}",
		},
	}
}

// GetAPIKey returns an API key by name.
// Returns empty string if not found.
func (c *Config) GetAPIKey(name string) string {
	return c.APIKeys[name]
}
