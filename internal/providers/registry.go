package providers

import (
	"errors"
	"fmt"
	"log/slog"
	"sync"
)

// Sentinel errors for the providers package.
var (
	// ErrLLMNotFound is returned when an LLM client is not found in the registry.
	ErrLLMNotFound = errors.New("LLM client not found")

	// ErrOCRNotFound is returned when an OCR provider is not found in the registry.
	ErrOCRNotFound = errors.New("OCR provider not found")

	// ErrTTSNotFound is returned when a TTS provider is not found in the registry.
	ErrTTSNotFound = errors.New("TTS provider not found")
)

// Registry holds references to LLM clients, OCR providers, and TTS providers.
// It supports config-driven instantiation, hot-reload, and provides thread-safe access.
type Registry struct {
	mu           sync.RWMutex
	llmClients   map[string]LLMClient
	ocrProviders map[string]OCRProvider
	ttsProviders map[string]TTSProvider
	logger       *slog.Logger
}

// NewRegistry creates a new empty provider registry.
func NewRegistry() *Registry {
	return &Registry{
		llmClients:   make(map[string]LLMClient),
		ocrProviders: make(map[string]OCRProvider),
		ttsProviders: make(map[string]TTSProvider),
		logger:       slog.Default(),
	}
}

// SetLogger sets the logger for the registry.
func (r *Registry) SetLogger(logger *slog.Logger) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.logger = logger
}

// RegisterLLM registers an LLM client by name.
func (r *Registry) RegisterLLM(name string, client LLMClient) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.llmClients[name] = client
	if r.logger != nil {
		r.logger.Info("registered LLM client", "name", name)
	}
}

// UnregisterLLM removes an LLM client by name.
func (r *Registry) UnregisterLLM(name string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.llmClients, name)
	if r.logger != nil {
		r.logger.Info("unregistered LLM client", "name", name)
	}
}

// RegisterOCR registers an OCR provider by name.
func (r *Registry) RegisterOCR(name string, provider OCRProvider) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.ocrProviders[name] = provider
	if r.logger != nil {
		r.logger.Info("registered OCR provider", "name", name)
	}
}

// UnregisterOCR removes an OCR provider by name.
func (r *Registry) UnregisterOCR(name string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.ocrProviders, name)
	if r.logger != nil {
		r.logger.Info("unregistered OCR provider", "name", name)
	}
}

// RegisterTTS registers a TTS provider by name.
func (r *Registry) RegisterTTS(name string, provider TTSProvider) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.ttsProviders[name] = provider
	if r.logger != nil {
		r.logger.Info("registered TTS provider", "name", name)
	}
}

// UnregisterTTS removes a TTS provider by name.
func (r *Registry) UnregisterTTS(name string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.ttsProviders, name)
	if r.logger != nil {
		r.logger.Info("unregistered TTS provider", "name", name)
	}
}

// GetLLM returns an LLM client by name.
func (r *Registry) GetLLM(name string) (LLMClient, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	client, ok := r.llmClients[name]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrLLMNotFound, name)
	}
	return client, nil
}

// GetOCR returns an OCR provider by name.
func (r *Registry) GetOCR(name string) (OCRProvider, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	provider, ok := r.ocrProviders[name]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrOCRNotFound, name)
	}
	return provider, nil
}

// GetTTS returns a TTS provider by name.
func (r *Registry) GetTTS(name string) (TTSProvider, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	provider, ok := r.ttsProviders[name]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrTTSNotFound, name)
	}
	return provider, nil
}

// ListLLM returns all registered LLM client names.
func (r *Registry) ListLLM() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.llmClients))
	for name := range r.llmClients {
		names = append(names, name)
	}
	return names
}

// ListOCR returns all registered OCR provider names.
func (r *Registry) ListOCR() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.ocrProviders))
	for name := range r.ocrProviders {
		names = append(names, name)
	}
	return names
}

// ListTTS returns all registered TTS provider names.
func (r *Registry) ListTTS() []string {
	r.mu.RLock()
	defer r.mu.RUnlock()
	names := make([]string, 0, len(r.ttsProviders))
	for name := range r.ttsProviders {
		names = append(names, name)
	}
	return names
}

// HasLLM checks if an LLM client is registered.
func (r *Registry) HasLLM(name string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, ok := r.llmClients[name]
	return ok
}

// HasOCR checks if an OCR provider is registered.
func (r *Registry) HasOCR(name string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, ok := r.ocrProviders[name]
	return ok
}

// HasTTS checks if a TTS provider is registered.
func (r *Registry) HasTTS(name string) bool {
	r.mu.RLock()
	defer r.mu.RUnlock()
	_, ok := r.ttsProviders[name]
	return ok
}

// LLMClients returns a map of all registered LLM clients.
// Used by Scheduler to create workers from providers.
func (r *Registry) LLMClients() map[string]LLMClient {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make(map[string]LLMClient, len(r.llmClients))
	for name, client := range r.llmClients {
		result[name] = client
	}
	return result
}

// OCRProviders returns a map of all registered OCR providers.
// Used by Scheduler to create workers from providers.
func (r *Registry) OCRProviders() map[string]OCRProvider {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make(map[string]OCRProvider, len(r.ocrProviders))
	for name, provider := range r.ocrProviders {
		result[name] = provider
	}
	return result
}

// TTSProviders returns a map of all registered TTS providers.
// Used by Scheduler to create workers from providers.
func (r *Registry) TTSProviders() map[string]TTSProvider {
	r.mu.RLock()
	defer r.mu.RUnlock()
	result := make(map[string]TTSProvider, len(r.ttsProviders))
	for name, provider := range r.ttsProviders {
		result[name] = provider
	}
	return result
}

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
	Type          string  // "mistral-ocr", "deepinfra"
	Model         string  // Model name (for deepinfra)
	APIKey        string  // Resolved API key
	RateLimit     float64 // Requests per second
	Enabled       bool
	IncludeImages bool // Whether to include base64 image data (Mistral only)
}

// LLMProviderConfig matches config.LLMProviderCfg with resolved API key.
type LLMProviderConfig struct {
	Type      string  // "openrouter"
	Model     string  // Model name
	APIKey    string  // Resolved API key
	RateLimit float64 // Requests per second
	Enabled   bool
}

// TTSProviderConfig matches config.TTSProviderCfg with resolved API key.
type TTSProviderConfig struct {
	Type         string  // "deepinfra-tts"
	Model        string  // Model name (e.g., "ResembleAI/chatterbox-turbo")
	Voice        string  // Voice ID
	Format       string  // Output format (mp3, wav, etc.)
	APIKey       string  // Resolved API key
	RateLimit    float64 // Requests per second
	Temperature  float64 // Generation temperature
	Exaggeration float64 // Emotion exaggeration factor
	CFG          float64 // Classifier-free guidance
	Enabled      bool
}

// NewRegistryFromConfig creates a registry with providers based on configuration.
// Only enabled providers with valid API keys will be registered.
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
		if !provCfg.Enabled || provCfg.APIKey == "" {
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
		if !provCfg.Enabled || provCfg.APIKey == "" {
			continue
		}
		wantOCR[name] = true

		existing, hasExisting := r.ocrProviders[name]
		if !hasExisting || needsOCRUpdate(existing, provCfg) {
			provider := createOCRProvider(provCfg)
			if provider != nil {
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
		if !provCfg.Enabled || provCfg.APIKey == "" {
			continue
		}
		client := createLLMClient(provCfg)
		if client != nil {
			r.llmClients[name] = client
		}
	}

	// Register OCR providers
	for name, provCfg := range cfg.OCRProviders {
		if !provCfg.Enabled || provCfg.APIKey == "" {
			continue
		}
		provider := createOCRProvider(provCfg)
		if provider != nil {
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
	switch cfg.Type {
	case "openrouter":
		return NewOpenRouterClient(OpenRouterConfig{
			APIKey:       cfg.APIKey,
			DefaultModel: cfg.Model,
			RPS:          cfg.RateLimit, // Pass RPS from config
		})
	default:
		return nil
	}
}

// createOCRProvider creates an OCR provider based on provider type.
func createOCRProvider(cfg OCRProviderConfig) OCRProvider {
	switch cfg.Type {
	case "mistral-ocr":
		return NewMistralOCRClient(MistralOCRConfig{
			APIKey:        cfg.APIKey,
			RateLimit:     cfg.RateLimit, // Pass rate limit from config
			IncludeImages: cfg.IncludeImages,
		})
	case "deepinfra":
		return NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey:    cfg.APIKey,
			Model:     cfg.Model,
			RateLimit: cfg.RateLimit, // Pass rate limit from config
		})
	default:
		return nil
	}
}

// needsLLMUpdate checks if an LLM client needs to be recreated.
func needsLLMUpdate(client LLMClient, cfg LLMProviderConfig) bool {
	switch c := client.(type) {
	case *OpenRouterClient:
		return c.apiKey != cfg.APIKey ||
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
		return p.apiKey != cfg.APIKey || p.rateLimit != cfg.RateLimit
	case *DeepInfraOCRClient:
		return p.apiKey != cfg.APIKey ||
			p.model != cfg.Model ||
			p.rateLimit != cfg.RateLimit
	default:
		return true
	}
}

// createTTSProvider creates a TTS provider based on provider type.
func createTTSProvider(cfg TTSProviderConfig) TTSProvider {
	switch cfg.Type {
	case "deepinfra-tts":
		return NewDeepInfraTTSClient(DeepInfraTTSConfig{
			APIKey:       cfg.APIKey,
			Model:        cfg.Model,
			Voice:        cfg.Voice,
			Format:       cfg.Format,
			RateLimit:    cfg.RateLimit,
			Temperature:  cfg.Temperature,
			Exaggeration: cfg.Exaggeration,
			CFG:          cfg.CFG,
		})
	default:
		return nil
	}
}

// needsTTSUpdate checks if a TTS provider needs to be recreated.
func needsTTSUpdate(provider TTSProvider, cfg TTSProviderConfig) bool {
	switch p := provider.(type) {
	case *DeepInfraTTSClient:
		return p.apiKey != cfg.APIKey ||
			p.model != cfg.Model ||
			p.voice != cfg.Voice ||
			p.format != cfg.Format ||
			p.rateLimit != cfg.RateLimit ||
			p.temperature != cfg.Temperature ||
			p.exaggeration != cfg.Exaggeration ||
			p.cfg != cfg.CFG
	default:
		return true
	}
}

