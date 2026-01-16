package config

// Config holds shelf configuration.
// Stored at: {storage_root}/config.yaml
type Config struct {
	OCRProviders map[string]OCRProviderCfg `mapstructure:"ocr_providers" yaml:"ocr_providers"`
	LLMProviders map[string]LLMProviderCfg `mapstructure:"llm_providers" yaml:"llm_providers"`
	TTSProviders map[string]TTSProviderCfg `mapstructure:"tts_providers" yaml:"tts_providers"`
	Defaults     DefaultsCfg               `mapstructure:"defaults" yaml:"defaults"`
	Defra        DefraConfig               `mapstructure:"defra" yaml:"defra"`
}

// OCRProviderCfg configures an OCR provider.
type OCRProviderCfg struct {
	Type          string  `mapstructure:"type" yaml:"type"`                     // "mistral-ocr", "deepinfra"
	Model         string  `mapstructure:"model" yaml:"model"`                   // Model name (for deepinfra)
	APIKey        string  `mapstructure:"api_key" yaml:"api_key"`               // API key (supports ${ENV_VAR} syntax)
	RateLimit     float64 `mapstructure:"rate_limit" yaml:"rate_limit"`         // Requests per second
	Enabled       bool    `mapstructure:"enabled" yaml:"enabled"`
	IncludeImages bool    `mapstructure:"include_images" yaml:"include_images"` // Extract images (Mistral only)
}

// LLMProviderCfg configures an LLM provider.
type LLMProviderCfg struct {
	Type      string  `mapstructure:"type" yaml:"type"`           // "openrouter"
	Model     string  `mapstructure:"model" yaml:"model"`         // Model name
	APIKey    string  `mapstructure:"api_key" yaml:"api_key"`     // API key (supports ${ENV_VAR} syntax)
	RateLimit float64 `mapstructure:"rate_limit" yaml:"rate_limit"` // Requests per second
	Enabled   bool    `mapstructure:"enabled" yaml:"enabled"`
}

// TTSProviderCfg configures a TTS provider (ElevenLabs only).
type TTSProviderCfg struct {
	Type       string  `mapstructure:"type" yaml:"type"`             // "elevenlabs"
	Model      string  `mapstructure:"model" yaml:"model"`           // e.g., "eleven_turbo_v2_5"
	Voice      string  `mapstructure:"voice" yaml:"voice"`           // Voice ID
	Format     string  `mapstructure:"format" yaml:"format"`         // Output format: mp3_44100_128, etc.
	APIKey     string  `mapstructure:"api_key" yaml:"api_key"`       // API key (supports ${ENV_VAR} syntax)
	RateLimit  float64 `mapstructure:"rate_limit" yaml:"rate_limit"` // Requests per second
	Stability  float64 `mapstructure:"stability" yaml:"stability"`   // Voice stability (0-1)
	Similarity float64 `mapstructure:"similarity" yaml:"similarity"` // Similarity boost (0-1)
	Style      float64 `mapstructure:"style" yaml:"style"`           // Style exaggeration (0-1)
	Speed      float64 `mapstructure:"speed" yaml:"speed"`           // Speaking speed (0.7-1.2)
	Enabled    bool    `mapstructure:"enabled" yaml:"enabled"`
}

// DefaultsCfg specifies default provider selections.
type DefaultsCfg struct {
	OCRProviders []string `mapstructure:"ocr_providers" yaml:"ocr_providers"` // Ordered list of OCR providers
	LLMProvider  string   `mapstructure:"llm_provider" yaml:"llm_provider"`   // Default LLM provider
	TTSProvider  string   `mapstructure:"tts_provider" yaml:"tts_provider"`   // Default TTS provider
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
				Type:          "mistral-ocr",
				APIKey:        "${MISTRAL_API_KEY}",
				RateLimit:     6.0, // 6 RPS
				Enabled:       true,
				IncludeImages: true, // Extract images from pages
			},
			"paddle": {
				Type:      "deepinfra",
				Model:     "PaddlePaddle/PaddleOCR-VL-0.9B",
				APIKey:    "${DEEPINFRA_API_KEY}",
				RateLimit: 10.0, // 10 RPS
				Enabled:   true,
			},
		},
		LLMProviders: map[string]LLMProviderCfg{
			"openrouter": {
				Type:      "openrouter",
				Model:     "x-ai/grok-4.1-fast",
				APIKey:    "${OPENROUTER_API_KEY}",
				RateLimit: 150.0, // 150 RPS
				Enabled:   true,
			},
		},
		TTSProviders: map[string]TTSProviderCfg{
			"elevenlabs": {
				Type:       "elevenlabs",
				Model:      "eleven_turbo_v2_5", // 40k char limit, 50% cheaper than multilingual_v2
				Format:     "mp3_44100_128",
				APIKey:     "${ELEVENLABS_API_KEY}",
				RateLimit:  2.0, // 2 RPS - ElevenLabs standard tier
				Stability:  0.5,
				Similarity: 0.75,
				Style:      0.0,
				Speed:      1.0,
				Enabled:    true,
			},
		},
		Defaults: DefaultsCfg{
			OCRProviders: []string{"mistral", "paddle"},
			LLMProvider:  "openrouter",
			TTSProvider:  "elevenlabs",
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

// GetTTSProvider returns a TTS provider config by name.
func (c *Config) GetTTSProvider(name string) (TTSProviderCfg, bool) {
	cfg, ok := c.TTSProviders[name]
	return cfg, ok
}

// EnabledTTSProviders returns all enabled TTS providers.
func (c *Config) EnabledTTSProviders() map[string]TTSProviderCfg {
	result := make(map[string]TTSProviderCfg)
	for name, cfg := range c.TTSProviders {
		if cfg.Enabled {
			result[name] = cfg
		}
	}
	return result
}
