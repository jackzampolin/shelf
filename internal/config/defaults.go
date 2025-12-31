package config

import (
	"context"
	"fmt"
	"log/slog"
)

// DefaultEntries returns the default configuration entries.
// These are seeded into DefraDB on first run.
func DefaultEntries() []Entry {
	return []Entry{
		// OCR Providers - Mistral
		{
			Key:         "providers.ocr.mistral.type",
			Value:       "mistral-ocr",
			Description: "OCR provider type for Mistral",
		},
		{
			Key:         "providers.ocr.mistral.api_key",
			Value:       "${MISTRAL_API_KEY}",
			Description: "Mistral API key (uses environment variable)",
		},
		{
			Key:         "providers.ocr.mistral.rate_limit",
			Value:       6.0,
			Description: "Rate limit in requests per second for Mistral",
		},
		{
			Key:         "providers.ocr.mistral.enabled",
			Value:       true,
			Description: "Whether Mistral OCR provider is enabled",
		},

		// OCR Providers - Paddle
		{
			Key:         "providers.ocr.paddle.type",
			Value:       "deepinfra",
			Description: "OCR provider type for Paddle (via DeepInfra)",
		},
		{
			Key:         "providers.ocr.paddle.model",
			Value:       "PaddlePaddle/PaddleOCR-VL-0.9B",
			Description: "Model name for Paddle OCR",
		},
		{
			Key:         "providers.ocr.paddle.api_key",
			Value:       "${DEEPINFRA_API_KEY}",
			Description: "DeepInfra API key (uses environment variable)",
		},
		{
			Key:         "providers.ocr.paddle.rate_limit",
			Value:       10.0,
			Description: "Rate limit in requests per second for Paddle",
		},
		{
			Key:         "providers.ocr.paddle.enabled",
			Value:       true,
			Description: "Whether Paddle OCR provider is enabled",
		},

		// LLM Providers - OpenRouter
		{
			Key:         "providers.llm.openrouter.type",
			Value:       "openrouter",
			Description: "LLM provider type for OpenRouter",
		},
		{
			Key:         "providers.llm.openrouter.model",
			Value:       "x-ai/grok-4.1-fast",
			Description: "Default model for OpenRouter",
		},
		{
			Key:         "providers.llm.openrouter.api_key",
			Value:       "${OPENROUTER_API_KEY}",
			Description: "OpenRouter API key (uses environment variable)",
		},
		{
			Key:         "providers.llm.openrouter.rate_limit",
			Value:       150.0,
			Description: "Rate limit in requests per second for OpenRouter",
		},
		{
			Key:         "providers.llm.openrouter.enabled",
			Value:       true,
			Description: "Whether OpenRouter LLM provider is enabled",
		},

		// Defaults
		{
			Key:         "defaults.ocr_providers",
			Value:       []string{"mistral", "paddle"},
			Description: "Ordered list of OCR providers to use",
		},
		{
			Key:         "defaults.llm_provider",
			Value:       "openrouter",
			Description: "Default LLM provider name",
		},
		{
			Key:         "defaults.max_workers",
			Value:       10,
			Description: "Maximum concurrent workers for processing",
		},
	}
}

// SeedDefaults seeds default configuration entries into the store.
// This is idempotent - existing entries are not overwritten.
func SeedDefaults(ctx context.Context, store Store, logger *slog.Logger) error {
	if logger == nil {
		logger = slog.Default()
	}

	defaults := DefaultEntries()
	seeded := 0
	skipped := 0

	for _, entry := range defaults {
		// Check if key already exists
		existing, err := store.Get(ctx, entry.Key)
		if err != nil {
			return fmt.Errorf("failed to check key %q: %w", entry.Key, err)
		}

		if existing != nil {
			skipped++
			continue
		}

		// Create the entry
		if err := store.Set(ctx, entry.Key, entry.Value, entry.Description); err != nil {
			return fmt.Errorf("failed to seed key %q: %w", entry.Key, err)
		}
		seeded++
	}

	if seeded > 0 {
		logger.Info("seeded default config entries", "seeded", seeded, "skipped", skipped)
	}
	return nil
}

// GetDefault returns the default value for a config key.
// Returns nil if no default exists for the key.
func GetDefault(key string) *Entry {
	for _, entry := range DefaultEntries() {
		if entry.Key == key {
			return &entry
		}
	}
	return nil
}

// ResetToDefault resets a config key to its default value.
// Returns error if no default exists for the key.
func ResetToDefault(ctx context.Context, store Store, key string) error {
	def := GetDefault(key)
	if def == nil {
		return fmt.Errorf("no default exists for key %q", key)
	}
	return store.Set(ctx, key, def.Value, def.Description)
}
