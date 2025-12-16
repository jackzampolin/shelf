package config

// Config holds shelf configuration.
// Stored at: {storage_root}/config.yaml
type Config struct {
	OCRProviders map[string]OCRProviderCfg `mapstructure:"ocr_providers" yaml:"ocr_providers"`
	LLMProviders map[string]LLMProviderCfg `mapstructure:"llm_providers" yaml:"llm_providers"`
	Defaults     DefaultsCfg               `mapstructure:"defaults" yaml:"defaults"`
	Defra        DefraConfig               `mapstructure:"defra" yaml:"defra"`
}

// OCRProviderCfg configures an OCR provider.
type OCRProviderCfg struct {
	Type      string  `mapstructure:"type" yaml:"type"`           // "mistral-ocr", "deepinfra"
	Model     string  `mapstructure:"model" yaml:"model"`         // Model name (for deepinfra)
	APIKey    string  `mapstructure:"api_key" yaml:"api_key"`     // API key (supports ${ENV_VAR} syntax)
	RateLimit float64 `mapstructure:"rate_limit" yaml:"rate_limit"` // Requests per second
	Enabled   bool    `mapstructure:"enabled" yaml:"enabled"`
}

// LLMProviderCfg configures an LLM provider.
type LLMProviderCfg struct {
	Type      string  `mapstructure:"type" yaml:"type"`           // "openrouter"
	Model     string  `mapstructure:"model" yaml:"model"`         // Model name
	APIKey    string  `mapstructure:"api_key" yaml:"api_key"`     // API key (supports ${ENV_VAR} syntax)
	RateLimit float64 `mapstructure:"rate_limit" yaml:"rate_limit"` // Requests per minute
	Enabled   bool    `mapstructure:"enabled" yaml:"enabled"`
}

// DefaultsCfg specifies default provider selections.
type DefaultsCfg struct {
	OCRProviders []string `mapstructure:"ocr_providers" yaml:"ocr_providers"` // Ordered list of OCR providers
	LLMProvider  string   `mapstructure:"llm_provider" yaml:"llm_provider"`   // Default LLM provider
	MaxWorkers   int      `mapstructure:"max_workers" yaml:"max_workers"`     // Max concurrent workers
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
		OCRProviders: map[string]OCRProviderCfg{
			"mistral": {
				Type:      "mistral-ocr",
				APIKey:    "${MISTRAL_API_KEY}",
				RateLimit: 6.0,
				Enabled:   true,
			},
		},
		LLMProviders: map[string]LLMProviderCfg{
			"openrouter": {
				Type:    "openrouter",
				Model:   "anthropic/claude-sonnet-4",
				APIKey:  "${OPENROUTER_API_KEY}",
				Enabled: true,
			},
		},
		Defaults: DefaultsCfg{
			OCRProviders: []string{"mistral"},
			LLMProvider:  "openrouter",
			MaxWorkers:   10,
		},
		Defra: DefraConfig{
			ContainerName: "shelf-defra",
			Image:         "sourcenetwork/defradb:latest",
			Port:          "9181",
		},
	}
}

// GetOCRProvider returns an OCR provider config by name.
func (c *Config) GetOCRProvider(name string) (OCRProviderCfg, bool) {
	cfg, ok := c.OCRProviders[name]
	return cfg, ok
}

// GetLLMProvider returns an LLM provider config by name.
func (c *Config) GetLLMProvider(name string) (LLMProviderCfg, bool) {
	cfg, ok := c.LLMProviders[name]
	return cfg, ok
}

// EnabledOCRProviders returns all enabled OCR providers.
func (c *Config) EnabledOCRProviders() map[string]OCRProviderCfg {
	result := make(map[string]OCRProviderCfg)
	for name, cfg := range c.OCRProviders {
		if cfg.Enabled {
			result[name] = cfg
		}
	}
	return result
}

// EnabledLLMProviders returns all enabled LLM providers.
func (c *Config) EnabledLLMProviders() map[string]LLMProviderCfg {
	result := make(map[string]LLMProviderCfg)
	for name, cfg := range c.LLMProviders {
		if cfg.Enabled {
			result[name] = cfg
		}
	}
	return result
}
