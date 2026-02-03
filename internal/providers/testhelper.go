package providers

import (
	"os"
)

// TestConfig holds provider configurations loaded from environment variables.
// This allows tests to use the same configuration pattern as production.
type TestConfig struct {
	OpenRouterAPIKey string
	MistralAPIKey    string
}

// LoadTestConfig loads provider API keys from environment variables.
// Returns a TestConfig with whatever keys are available.
func LoadTestConfig() TestConfig {
	return TestConfig{
		OpenRouterAPIKey: os.Getenv("OPENROUTER_API_KEY"),
		MistralAPIKey:    os.Getenv("MISTRAL_API_KEY"),
	}
}

// HasOpenRouter returns true if OpenRouter API key is configured.
func (c TestConfig) HasOpenRouter() bool {
	return c.OpenRouterAPIKey != ""
}

// HasMistral returns true if Mistral API key is configured.
func (c TestConfig) HasMistral() bool {
	return c.MistralAPIKey != ""
}

// HasAnyOCR returns true if any OCR provider is configured.
func (c TestConfig) HasAnyOCR() bool {
	return c.HasMistral()
}

// HasAnyLLM returns true if any LLM provider is configured.
func (c TestConfig) HasAnyLLM() bool {
	return c.HasOpenRouter()
}

// NewOpenRouterClient creates an OpenRouter client from test config.
// Returns nil if not configured.
func (c TestConfig) NewOpenRouterClient() *OpenRouterClient {
	if !c.HasOpenRouter() {
		return nil
	}
	return NewOpenRouterClient(OpenRouterConfig{
		APIKey: c.OpenRouterAPIKey,
	})
}

// NewMistralOCRClient creates a Mistral OCR client from test config.
// Returns nil if not configured.
func (c TestConfig) NewMistralOCRClient() *MistralOCRClient {
	if !c.HasMistral() {
		return nil
	}
	return NewMistralOCRClient(MistralOCRConfig{
		APIKey: c.MistralAPIKey,
	})
}

// ToRegistryConfig converts test config to a RegistryConfig for the provider registry.
// Only includes providers that have API keys configured.
func (c TestConfig) ToRegistryConfig() RegistryConfig {
	cfg := RegistryConfig{
		OCRProviders: make(map[string]OCRProviderConfig),
		LLMProviders: make(map[string]LLMProviderConfig),
	}

	if c.HasOpenRouter() {
		cfg.LLMProviders["openrouter"] = LLMProviderConfig{
			Type:      "openrouter",
			APIKey:    c.OpenRouterAPIKey,
			RateLimit: 60,
			Enabled:   true,
		}
	}

	if c.HasMistral() {
		cfg.OCRProviders["mistral"] = OCRProviderConfig{
			Type:      "mistral-ocr",
			APIKey:    c.MistralAPIKey,
			RateLimit: 6,
			Enabled:   true,
		}
	}

	return cfg
}
