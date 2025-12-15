package config

// Config holds shelf configuration.
// Stored at: {storage_root}/config.yaml
type Config struct {
	APIKeys map[string]string `mapstructure:"api_keys" yaml:"api_keys"`
	Defra   DefraConfig       `mapstructure:"defra" yaml:"defra"`
}

// DefraConfig holds DefraDB container configuration.
type DefraConfig struct {
	// ContainerName is the Docker container name (default: shelf-defra)
	ContainerName string `mapstructure:"container_name" yaml:"container_name"`
	// Image is the Docker image to use (default: sourcenetwork/defradb:latest)
	Image string `mapstructure:"image" yaml:"image"`
	// Port is the host port to bind (default: 9181)
	Port string `mapstructure:"port" yaml:"port"`
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
		Defra: DefraConfig{
			ContainerName: "shelf-defra",
			Image:         "sourcenetwork/defradb:latest",
			Port:          "9181",
		},
	}
}

// GetAPIKey returns an API key by name.
// Returns empty string if not found.
func (c *Config) GetAPIKey(name string) string {
	return c.APIKeys[name]
}
