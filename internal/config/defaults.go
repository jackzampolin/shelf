package config

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
)

// ErrNoDefault is returned when no default value exists for a config key.
var ErrNoDefault = errors.New("no default exists")

// DefaultEntries returns the default configuration entries.
// These are seeded into DefraDB on first run.
func DefaultEntries() []Entry {
	return []Entry{
		// ===================
		// OCR Providers
		// ===================

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
		{
			Key:         "providers.ocr.mistral.timeout_seconds",
			Value:       500,
			Description: "HTTP timeout in seconds for Mistral OCR requests",
		},
		{
			Key:         "providers.ocr.mistral.max_retries",
			Value:       7,
			Description: "Maximum retry attempts for failed Mistral requests",
		},
		{
			Key:         "providers.ocr.mistral.max_concurrency",
			Value:       30,
			Description: "Maximum concurrent requests to Mistral",
		},

		// ===================
		// LLM Providers
		// ===================

		// LLM Providers - OpenRouter
		{
			Key:         "providers.llm.openrouter.type",
			Value:       "openrouter",
			Description: "LLM provider type for OpenRouter",
		},
		{
			Key:         "providers.llm.openrouter.model",
			Value:       "anthropic/claude-opus-4.6",
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
		{
			Key:         "providers.llm.openrouter.timeout_seconds",
			Value:       500,
			Description: "HTTP timeout in seconds for OpenRouter requests",
		},
		{
			Key:         "providers.llm.openrouter.max_retries",
			Value:       7,
			Description: "Maximum retry attempts for failed OpenRouter requests",
		},
		{
			Key:         "providers.llm.openrouter.max_concurrency",
			Value:       30,
			Description: "Maximum concurrent requests to OpenRouter",
		},

		// ===================
		// TTS Providers
		// ===================

		// TTS Providers - ElevenLabs
		{
			Key:         "providers.tts.elevenlabs.type",
			Value:       "elevenlabs",
			Description: "TTS provider type for ElevenLabs",
		},
		{
			Key:         "providers.tts.elevenlabs.model",
			Value:       "eleven_turbo_v2_5",
			Description: "Model name for ElevenLabs TTS (40k char limit, 50% cheaper)",
		},
		{
			Key:         "providers.tts.elevenlabs.api_key",
			Value:       "${ELEVENLABS_API_KEY}",
			Description: "ElevenLabs API key (uses environment variable)",
		},
		{
			Key:         "providers.tts.elevenlabs.rate_limit",
			Value:       10.0,
			Description: "Rate limit in requests per second for ElevenLabs",
		},
		{
			Key:         "providers.tts.elevenlabs.max_concurrency",
			Value:       10,
			Description: "Maximum concurrent requests to ElevenLabs",
		},
		{
			Key:         "providers.tts.elevenlabs.enabled",
			Value:       true,
			Description: "Whether ElevenLabs TTS provider is enabled",
		},
		{
			Key:         "providers.tts.elevenlabs.format",
			Value:       "mp3_44100_128",
			Description: "Default audio output format",
		},
		{
			Key:         "providers.tts.elevenlabs.stability",
			Value:       0.5,
			Description: "Voice stability (0-1)",
		},
		{
			Key:         "providers.tts.elevenlabs.similarity",
			Value:       0.75,
			Description: "Similarity boost (0-1)",
		},

		// TTS Providers - OpenAI
		{
			Key:         "providers.tts.openai.type",
			Value:       "openai",
			Description: "TTS provider type for OpenAI",
		},
		{
			Key:         "providers.tts.openai.model",
			Value:       "tts-1-hd",
			Description: "Default OpenAI TTS model",
		},
		{
			Key:         "providers.tts.openai.voice",
			Value:       "onyx",
			Description: "Default OpenAI TTS voice",
		},
		{
			Key:         "providers.tts.openai.api_key",
			Value:       "${OPENAI_API_KEY}",
			Description: "OpenAI API key (uses environment variable)",
		},
		{
			Key:         "providers.tts.openai.rate_limit",
			Value:       8.0,
			Description: "Rate limit in requests per second for OpenAI TTS",
		},
		{
			Key:         "providers.tts.openai.max_concurrency",
			Value:       30,
			Description: "Maximum concurrent requests to OpenAI TTS",
		},
		{
			Key:         "providers.tts.openai.enabled",
			Value:       true,
			Description: "Whether OpenAI TTS provider is enabled",
		},
		{
			Key:         "providers.tts.openai.format",
			Value:       "mp3",
			Description: "Default OpenAI audio output format",
		},
		{
			Key:         "providers.tts.openai.speed",
			Value:       1.0,
			Description: "Default OpenAI speech speed",
		},

		// ===================
		// Pipeline Defaults
		// ===================
		{
			Key:         "defaults.ocr_providers",
			Value:       []string{"mistral"},
			Description: "Ordered list of OCR providers",
		},
		{
			Key:         "defaults.llm_provider",
			Value:       "openrouter",
			Description: "Default LLM provider used for pipeline stages (metadata, toc, structure)",
		},
		{
			Key:         "defaults.tts_provider",
			Value:       "openai",
			Description: "Default TTS provider for audiobook generation",
		},
		{
			Key:         "defaults.openai_tts_instructions",
			Value:       "",
			Description: "Optional instructions for OpenAI gpt-4o-mini-tts generation",
		},
		{
			Key:         "defaults.debug_agents",
			Value:       false,
			Description: "Enable verbose debug logging for agent executions",
		},
	}
}

// DefaultEntriesFromConfig returns default entries with provider/default values
// overlaid from the loaded config file. It is used on first boot so a clean DB
// reflects the active profile instead of hardcoded cloud-provider defaults.
func DefaultEntriesFromConfig(cfg *Config) []Entry {
	entries := DefaultEntries()
	if cfg == nil {
		return entries
	}

	indexByKey := make(map[string]int, len(entries))
	for i, entry := range entries {
		indexByKey[entry.Key] = i
	}
	upsert := func(key string, value any, description string) {
		entry := Entry{Key: key, Value: value, Description: description}
		if idx, ok := indexByKey[key]; ok {
			entries[idx] = entry
			return
		}
		indexByKey[key] = len(entries)
		entries = append(entries, entry)
	}

	for name, ocr := range cfg.OCRProviders {
		prefix := "providers.ocr." + name + "."
		upsert(prefix+"type", ocr.Type, "OCR provider type")
		upsert(prefix+"api_key", ocr.APIKey, "OCR provider API key")
		upsert(prefix+"rate_limit", ocr.RateLimit, "OCR provider request rate limit")
		upsert(prefix+"enabled", ocr.Enabled, "Whether OCR provider is enabled")
		upsert(prefix+"include_images", ocr.IncludeImages, "Whether OCR should include extracted images")
		upsert(prefix+"include_headers_footers", ocr.IncludeHeadersFooters, "Whether OCR keeps page headers and footers in markdown")
		upsert(prefix+"max_output_tokens", ocr.MaxOutputTokens, "Maximum OCR output tokens per page")
		upsert(prefix+"timeout_seconds", ocr.TimeoutSeconds, "OCR HTTP timeout in seconds")
		upsert(prefix+"temperature", ocr.Temperature, "OCR generation temperature")
		upsert(prefix+"top_p", ocr.TopP, "OCR nucleus sampling value")
		upsert(prefix+"base_urls", ocr.BaseURLs, "OCR provider base URLs")
		upsert(prefix+"max_concurrency", ocr.MaxConcurrency, "Maximum concurrent OCR requests")
		upsert(prefix+"max_retries", ocr.MaxRetries, "Maximum provider-level OCR retries")
	}

	for name, llm := range cfg.LLMProviders {
		prefix := "providers.llm." + name + "."
		upsert(prefix+"type", llm.Type, "LLM provider type")
		upsert(prefix+"model", llm.Model, "LLM model name")
		upsert(prefix+"api_key", llm.APIKey, "LLM provider API key")
		upsert(prefix+"rate_limit", llm.RateLimit, "LLM provider request rate limit")
		upsert(prefix+"enabled", llm.Enabled, "Whether LLM provider is enabled")
		upsert(prefix+"base_urls", llm.BaseURLs, "LLM provider base URLs")
		upsert(prefix+"max_concurrency", llm.MaxConcurrency, "Maximum concurrent LLM requests")
		upsert(prefix+"timeout_seconds", llm.TimeoutSeconds, "LLM HTTP timeout in seconds")
		upsert(prefix+"max_retries", llm.MaxRetries, "Maximum provider-level LLM attempts")
	}

	for name, tts := range cfg.TTSProviders {
		prefix := "providers.tts." + name + "."
		upsert(prefix+"type", tts.Type, "TTS provider type")
		upsert(prefix+"model", tts.Model, "TTS model name")
		upsert(prefix+"voice", tts.Voice, "TTS voice")
		upsert(prefix+"format", tts.Format, "TTS output format")
		upsert(prefix+"instructions", tts.Instructions, "TTS generation instructions")
		upsert(prefix+"api_key", tts.APIKey, "TTS provider API key")
		upsert(prefix+"rate_limit", tts.RateLimit, "TTS provider request rate limit")
		upsert(prefix+"stability", tts.Stability, "Voice stability")
		upsert(prefix+"similarity", tts.Similarity, "Voice similarity boost")
		upsert(prefix+"style", tts.Style, "Voice style exaggeration")
		upsert(prefix+"speed", tts.Speed, "Speech speed")
		upsert(prefix+"enabled", tts.Enabled, "Whether TTS provider is enabled")
	}

	if len(cfg.Defaults.OCRProviders) > 0 {
		upsert("defaults.ocr_providers", cfg.Defaults.OCRProviders, "Ordered list of OCR providers")
	}
	if cfg.Defaults.LLMProvider != "" {
		upsert("defaults.llm_provider", cfg.Defaults.LLMProvider, "Default LLM provider used for pipeline stages (metadata, toc, structure)")
	}
	if cfg.Defaults.TTSProvider != "" {
		upsert("defaults.tts_provider", cfg.Defaults.TTSProvider, "Default TTS provider for audiobook generation")
	}
	upsert("defaults.openai_tts_instructions", cfg.Defaults.OpenAITTSInstructions, "Optional instructions for OpenAI gpt-4o-mini-tts generation")

	return entries
}

// SeedDefaults seeds default configuration entries into the store.
// This is idempotent - existing entries are not overwritten.
func SeedDefaults(ctx context.Context, store Store, logger *slog.Logger) error {
	return seedEntries(ctx, store, logger, DefaultEntries())
}

// SeedDefaultsFromConfig seeds defaults overlaid with config-file provider
// settings. Existing entries are not overwritten.
func SeedDefaultsFromConfig(ctx context.Context, store Store, logger *slog.Logger, cfg *Config) error {
	return seedEntries(ctx, store, logger, DefaultEntriesFromConfig(cfg))
}

func seedEntries(ctx context.Context, store Store, logger *slog.Logger, defaults []Entry) error {
	if logger == nil {
		logger = slog.Default()
	}

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
// Returns ErrNoDefault if no default exists for the key.
func ResetToDefault(ctx context.Context, store Store, key string) error {
	def := GetDefault(key)
	if def == nil {
		return fmt.Errorf("%w for key %q", ErrNoDefault, key)
	}
	return store.Set(ctx, key, def.Value, def.Description)
}
