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

type ocrLoggerSetter interface {
	SetLogger(*slog.Logger)
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
	if logger == nil {
		return
	}
	r.logger = logger
	for name, provider := range r.ocrProviders {
		if lp, ok := provider.(ocrLoggerSetter); ok {
			lp.SetLogger(r.logger.With("ocr_provider", name))
		}
	}
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
	if lp, ok := provider.(ocrLoggerSetter); ok && r.logger != nil {
		lp.SetLogger(r.logger.With("ocr_provider", name))
	}
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
