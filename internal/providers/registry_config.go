package providers

import (
	"time"
)

// RegistryConfig defines the providers to instantiate from config.
// This mirrors the config.Config structure for provider setup.
type RegistryConfig struct {
	// APIKeys maps provider names to resolved API keys
	APIKeys map[string]string

	// OCRProviders maps provider names to their config
	OCRProviders map[string]OCRProviderConfig

	// LLMProviders maps provider names to their config
	LLMProviders map[string]LLMProviderConfig

	// TTSProviders maps provider names to their config
	TTSProviders map[string]TTSProviderConfig
}

// OCRProviderConfig matches config.OCRProviderCfg with resolved API key.
type OCRProviderConfig struct {
	Type                  string  // "mistral-ocr" or "chandra"
	APIKey                string  // Resolved API key
	RateLimit             float64 // Requests per second
	Enabled               bool
	IncludeImages         bool     // Whether to include extracted image data when supported
	IncludeHeadersFooters bool     // Whether to keep page furniture in OCR markdown when supported
	MaxOutputTokens       int      // Max OCR output tokens per page (0 = provider default)
	TimeoutSeconds        int      // OCR HTTP timeout in seconds (0 = provider default)
	Temperature           float64  // OCR generation temperature
	TopP                  float64  // OCR nucleus sampling value
	BaseURLs              []string // Optional self-hosted endpoints
	MaxConcurrency        int      // Max concurrent in-flight requests (0 = provider default)
	MaxRetries            int      // Max provider retries (0 = provider default)
}

// LLMProviderConfig matches config.LLMProviderCfg with resolved API key.
type LLMProviderConfig struct {
	Type           string  // "openrouter"
	Model          string  // Model name
	APIKey         string  // Resolved API key
	RateLimit      float64 // Requests per second
	Enabled        bool
	BaseURLs       []string // Optional self-hosted endpoints
	MaxConcurrency int      // Max concurrent in-flight requests (0 = provider default)
	TimeoutSeconds int      // HTTP timeout in seconds (0 = provider default)
	MaxRetries     int      // Provider attempts per request (0 = provider default)
}

// TTSProviderConfig matches config.TTSProviderCfg with resolved API key.
type TTSProviderConfig struct {
	Type         string  // "elevenlabs" or "openai"
	Model        string  // Model name (provider-specific)
	Voice        string  // Voice ID
	Format       string  // Output format (mp3_44100_128, etc.)
	Instructions string  // Optional provider-specific instructions (OpenAI gpt-4o-mini-tts)
	APIKey       string  // Resolved API key
	RateLimit    float64 // Requests per second
	Stability    float64 // Voice stability (0-1)
	Similarity   float64 // Similarity boost (0-1)
	Style        float64 // Style exaggeration (0-1)
	Speed        float64 // Speaking speed (0.7-1.2)
	Enabled      bool
}

// NewRegistryFromConfig creates a registry with providers based on configuration.
// Only enabled providers with valid API keys or configured base URLs will be registered.
func NewRegistryFromConfig(cfg RegistryConfig) *Registry {
	r := NewRegistry()
	r.applyConfig(cfg)
	return r
}

// Reload updates the registry based on new configuration.
// Providers that are no longer configured will be unregistered.
// Providers with changed settings will be re-registered.
func (r *Registry) Reload(cfg RegistryConfig) {
	r.mu.Lock()
	defer r.mu.Unlock()

	// Track which providers should exist
	wantLLM := make(map[string]bool)
	wantOCR := make(map[string]bool)
	wantTTS := make(map[string]bool)

	// Process LLM providers
	for name, provCfg := range cfg.LLMProviders {
		if !provCfg.Enabled || (provCfg.APIKey == "" && len(provCfg.BaseURLs) == 0) {
			continue
		}
		wantLLM[name] = true

		existing, hasExisting := r.llmClients[name]
		if !hasExisting || needsLLMUpdate(existing, provCfg) {
			client := createLLMClient(provCfg)
			if client != nil {
				r.llmClients[name] = client
				if r.logger != nil {
					if hasExisting {
						r.logger.Info("updated LLM client", "name", name, "type", provCfg.Type)
					} else {
						r.logger.Info("registered LLM client", "name", name, "type", provCfg.Type)
					}
				}
			}
		}
	}

	// Process OCR providers
	for name, provCfg := range cfg.OCRProviders {
		if !provCfg.Enabled || (provCfg.APIKey == "" && len(provCfg.BaseURLs) == 0) {
			continue
		}
		wantOCR[name] = true

		existing, hasExisting := r.ocrProviders[name]
		if !hasExisting || needsOCRUpdate(existing, provCfg) {
			provider := createOCRProvider(provCfg)
			if provider != nil {
				if lp, ok := provider.(ocrLoggerSetter); ok && r.logger != nil {
					lp.SetLogger(r.logger.With("ocr_provider", name))
				}
				r.ocrProviders[name] = provider
				if r.logger != nil {
					if hasExisting {
						r.logger.Info("updated OCR provider", "name", name, "type", provCfg.Type)
					} else {
						r.logger.Info("registered OCR provider", "name", name, "type", provCfg.Type)
					}
				}
			}
		}
	}

	// Process TTS providers
	for name, provCfg := range cfg.TTSProviders {
		if !provCfg.Enabled || provCfg.APIKey == "" {
			continue
		}
		wantTTS[name] = true

		existing, hasExisting := r.ttsProviders[name]
		if !hasExisting || needsTTSUpdate(existing, provCfg) {
			provider := createTTSProvider(provCfg)
			if provider != nil {
				r.ttsProviders[name] = provider
				if r.logger != nil {
					if hasExisting {
						r.logger.Info("updated TTS provider", "name", name, "type", provCfg.Type)
					} else {
						r.logger.Info("registered TTS provider", "name", name, "type", provCfg.Type)
					}
				}
			}
		}
	}

	// Remove providers that are no longer configured
	for name := range r.llmClients {
		if !wantLLM[name] {
			delete(r.llmClients, name)
			if r.logger != nil {
				r.logger.Info("unregistered LLM client", "name", name)
			}
		}
	}
	for name := range r.ocrProviders {
		if !wantOCR[name] {
			delete(r.ocrProviders, name)
			if r.logger != nil {
				r.logger.Info("unregistered OCR provider", "name", name)
			}
		}
	}
	for name := range r.ttsProviders {
		if !wantTTS[name] {
			delete(r.ttsProviders, name)
			if r.logger != nil {
				r.logger.Info("unregistered TTS provider", "name", name)
			}
		}
	}
}

// applyConfig applies configuration without locking (used during init).
func (r *Registry) applyConfig(cfg RegistryConfig) {
	// Register LLM providers
	for name, provCfg := range cfg.LLMProviders {
		if !provCfg.Enabled || (provCfg.APIKey == "" && len(provCfg.BaseURLs) == 0) {
			continue
		}
		client := createLLMClient(provCfg)
		if client != nil {
			r.llmClients[name] = client
		}
	}

	// Register OCR providers
	for name, provCfg := range cfg.OCRProviders {
		if !provCfg.Enabled || (provCfg.APIKey == "" && len(provCfg.BaseURLs) == 0) {
			continue
		}
		provider := createOCRProvider(provCfg)
		if provider != nil {
			if lp, ok := provider.(ocrLoggerSetter); ok && r.logger != nil {
				lp.SetLogger(r.logger.With("ocr_provider", name))
			}
			r.ocrProviders[name] = provider
		}
	}

	// Register TTS providers
	for name, provCfg := range cfg.TTSProviders {
		if !provCfg.Enabled || provCfg.APIKey == "" {
			continue
		}
		provider := createTTSProvider(provCfg)
		if provider != nil {
			r.ttsProviders[name] = provider
		}
	}
}

// createLLMClient creates an LLM client based on provider type.
func createLLMClient(cfg LLMProviderConfig) LLMClient {
	timeout := time.Duration(cfg.TimeoutSeconds) * time.Second
	switch cfg.Type {
	case "openrouter":
		orc := OpenRouterConfig{
			APIKey:       cfg.APIKey,
			DefaultModel: cfg.Model,
			RPS:          cfg.RateLimit, // Pass RPS from config
			Timeout:      timeout,
			MaxRetries:   cfg.MaxRetries,
		}
		if len(cfg.BaseURLs) > 0 {
			orc.BaseURL = cfg.BaseURLs[0]
		}
		return NewOpenRouterClient(orc)
	case "openai-compat", "vllm":
		return NewOpenAICompatClient(OpenAICompatConfig{
			Name:           cfg.Type,
			BaseURLs:       cfg.BaseURLs,
			APIKey:         cfg.APIKey,
			DefaultModel:   cfg.Model,
			RPS:            cfg.RateLimit,
			MaxConcurrency: cfg.MaxConcurrency,
			Timeout:        timeout,
			MaxRetries:     cfg.MaxRetries,
		})
	default:
		return nil
	}
}

// createOCRProvider creates an OCR provider based on provider type.
func createOCRProvider(cfg OCRProviderConfig) OCRProvider {
	switch cfg.Type {
	case "mistral-ocr":
		moc := MistralOCRConfig{
			APIKey:        cfg.APIKey,
			RateLimit:     cfg.RateLimit,
			IncludeImages: cfg.IncludeImages,
		}
		if len(cfg.BaseURLs) > 0 {
			moc.BaseURL = cfg.BaseURLs[0]
		}
		return NewMistralOCRClient(moc)
	case "chandra":
		timeout := time.Duration(cfg.TimeoutSeconds) * time.Second
		return NewChandraOCRClient(ChandraOCRConfig{
			Name:                  cfg.Type,
			BaseURLs:              cfg.BaseURLs,
			APIKey:                cfg.APIKey,
			RateLimit:             cfg.RateLimit,
			IncludeImages:         cfg.IncludeImages,
			IncludeHeadersFooters: cfg.IncludeHeadersFooters,
			MaxOutputTokens:       cfg.MaxOutputTokens,
			Temperature:           cfg.Temperature,
			TopP:                  cfg.TopP,
			MaxConcurrency:        cfg.MaxConcurrency,
			MaxRetries:            cfg.MaxRetries,
			Timeout:               timeout,
		})
	default:
		return nil
	}
}

// needsLLMUpdate checks if an LLM client needs to be recreated.
func needsLLMUpdate(client LLMClient, cfg LLMProviderConfig) bool {
	switch c := client.(type) {
	case *OpenAIChatClient:
		baseURL := OpenRouterBaseURL
		if len(cfg.BaseURLs) > 0 {
			baseURL = cfg.BaseURLs[0]
		}
		return c.apiKey != cfg.APIKey ||
			c.baseURL != baseURL ||
			c.defaultModel != cfg.Model ||
			c.rps != cfg.RateLimit
	default:
		return true
	}
}

// needsOCRUpdate checks if an OCR provider needs to be recreated.
func needsOCRUpdate(provider OCRProvider, cfg OCRProviderConfig) bool {
	switch p := provider.(type) {
	case *MistralOCRClient:
		baseURL := MistralOCRBaseURL
		if len(cfg.BaseURLs) > 0 {
			baseURL = cfg.BaseURLs[0]
		}
		return p.apiKey != cfg.APIKey ||
			p.baseURL != baseURL ||
			p.rateLimit != cfg.RateLimit
	case *ChandraOCRClient:
		_ = p
		return true
	}
	return true
}

// createTTSProvider creates a TTS provider based on provider type.
func createTTSProvider(cfg TTSProviderConfig) TTSProvider {
	switch cfg.Type {
	case "elevenlabs":
		return NewElevenLabsTTSClient(ElevenLabsTTSConfig{
			APIKey:     cfg.APIKey,
			Model:      cfg.Model,
			Voice:      cfg.Voice,
			Format:     cfg.Format,
			RateLimit:  cfg.RateLimit,
			Stability:  cfg.Stability,
			Similarity: cfg.Similarity,
			Style:      cfg.Style,
			Speed:      cfg.Speed,
		})
	case "openai":
		return NewOpenAITTSClient(OpenAITTSConfig{
			APIKey:       cfg.APIKey,
			Model:        cfg.Model,
			Voice:        cfg.Voice,
			Speed:        cfg.Speed,
			Instructions: cfg.Instructions,
			RateLimit:    cfg.RateLimit,
		})
	default:
		return nil
	}
}

// needsTTSUpdate checks if a TTS provider needs to be recreated.
func needsTTSUpdate(provider TTSProvider, cfg TTSProviderConfig) bool {
	switch p := provider.(type) {
	case *ElevenLabsTTSClient:
		return p.apiKey != cfg.APIKey ||
			p.model != cfg.Model ||
			p.voice != cfg.Voice ||
			p.format != cfg.Format ||
			p.rateLimit != cfg.RateLimit ||
			p.stability != cfg.Stability ||
			p.similarity != cfg.Similarity ||
			p.style != cfg.Style ||
			p.speed != cfg.Speed
	case *OpenAITTSClient:
		return p.apiKey != cfg.APIKey ||
			p.model != cfg.Model ||
			p.voice != cfg.Voice ||
			p.speed != cfg.Speed ||
			p.instructions != cfg.Instructions ||
			p.rateLimit != cfg.RateLimit
	default:
		return true
	}
}
