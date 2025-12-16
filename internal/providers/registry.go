package providers

import (
	"fmt"
	"log/slog"
	"sync"
)

// Registry holds references to LLM clients and OCR providers.
// It supports config-driven instantiation, hot-reload, and provides thread-safe access.
type Registry struct {
	mu           sync.RWMutex
	llmClients   map[string]LLMClient
	ocrProviders map[string]OCRProvider
	logger       *slog.Logger
}

// NewRegistry creates a new empty provider registry.
func NewRegistry() *Registry {
	return &Registry{
		llmClients:   make(map[string]LLMClient),
		ocrProviders: make(map[string]OCRProvider),
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

// GetLLM returns an LLM client by name.
func (r *Registry) GetLLM(name string) (LLMClient, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	client, ok := r.llmClients[name]
	if !ok {
		return nil, fmt.Errorf("LLM client not found: %s", name)
	}
	return client, nil
}

// GetOCR returns an OCR provider by name.
func (r *Registry) GetOCR(name string) (OCRProvider, error) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	provider, ok := r.ocrProviders[name]
	if !ok {
		return nil, fmt.Errorf("OCR provider not found: %s", name)
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

// RegistryConfig defines the providers to instantiate from config.
// This mirrors the config.Config structure for provider setup.
type RegistryConfig struct {
	// APIKeys maps provider names to resolved API keys
	APIKeys map[string]string

	// OCRProviders maps provider names to their config
	OCRProviders map[string]OCRProviderConfig

	// LLMProviders maps provider names to their config
	LLMProviders map[string]LLMProviderConfig
}

// OCRProviderConfig matches config.OCRProviderCfg with resolved API key.
type OCRProviderConfig struct {
	Type      string  // "mistral-ocr", "deepinfra"
	Model     string  // Model name (for deepinfra)
	APIKey    string  // Resolved API key
	RateLimit float64 // Requests per second
	Enabled   bool
}

// LLMProviderConfig matches config.LLMProviderCfg with resolved API key.
type LLMProviderConfig struct {
	Type      string  // "openrouter"
	Model     string  // Model name
	APIKey    string  // Resolved API key
	RateLimit float64 // Requests per minute
	Enabled   bool
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
}

// createLLMClient creates an LLM client based on provider type.
func createLLMClient(cfg LLMProviderConfig) LLMClient {
	switch cfg.Type {
	case "openrouter":
		return NewOpenRouterClient(OpenRouterConfig{
			APIKey:       cfg.APIKey,
			DefaultModel: cfg.Model,
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
			APIKey: cfg.APIKey,
		})
	case "deepinfra":
		return NewDeepInfraOCRClient(DeepInfraOCRConfig{
			APIKey: cfg.APIKey,
			Model:  cfg.Model,
		})
	default:
		return nil
	}
}

// needsLLMUpdate checks if an LLM client needs to be recreated.
func needsLLMUpdate(client LLMClient, cfg LLMProviderConfig) bool {
	switch c := client.(type) {
	case *OpenRouterClient:
		return c.apiKey != cfg.APIKey || c.defaultModel != cfg.Model
	default:
		return true
	}
}

// needsOCRUpdate checks if an OCR provider needs to be recreated.
func needsOCRUpdate(provider OCRProvider, cfg OCRProviderConfig) bool {
	switch p := provider.(type) {
	case *MistralOCRClient:
		return p.apiKey != cfg.APIKey
	case *DeepInfraOCRClient:
		return p.apiKey != cfg.APIKey || p.model != cfg.Model
	default:
		return true
	}
}

// RegistryConfigFromResolved converts config-resolved providers to RegistryConfig.
// This allows the config package to provide resolved provider info without
// creating a circular dependency.
func RegistryConfigFromResolved(
	ocrProviders map[string]struct {
		Type      string
		Model     string
		APIKey    string
		RateLimit float64
		Enabled   bool
	},
	llmProviders map[string]struct {
		Type      string
		Model     string
		APIKey    string
		RateLimit float64
		Enabled   bool
	},
) RegistryConfig {
	cfg := RegistryConfig{
		OCRProviders: make(map[string]OCRProviderConfig),
		LLMProviders: make(map[string]LLMProviderConfig),
	}

	for name, ocr := range ocrProviders {
		cfg.OCRProviders[name] = OCRProviderConfig{
			Type:      ocr.Type,
			Model:     ocr.Model,
			APIKey:    ocr.APIKey,
			RateLimit: ocr.RateLimit,
			Enabled:   ocr.Enabled,
		}
	}

	for name, llm := range llmProviders {
		cfg.LLMProviders[name] = LLMProviderConfig{
			Type:      llm.Type,
			Model:     llm.Model,
			APIKey:    llm.APIKey,
			RateLimit: llm.RateLimit,
			Enabled:   llm.Enabled,
		}
	}

	return cfg
}
