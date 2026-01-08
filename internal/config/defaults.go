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
		{
			Key:         "providers.ocr.paddle.timeout_seconds",
			Value:       500,
			Description: "HTTP timeout in seconds for Paddle OCR requests",
		},
		{
			Key:         "providers.ocr.paddle.max_retries",
			Value:       7,
			Description: "Maximum retry attempts for failed Paddle requests",
		},
		{
			Key:         "providers.ocr.paddle.max_concurrency",
			Value:       30,
			Description: "Maximum concurrent requests to Paddle",
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
		// Pipeline Defaults
		// ===================
		{
			Key:         "defaults.ocr_providers",
			Value:       []string{"mistral", "paddle"},
			Description: "Ordered list of OCR providers to use for blending",
		},
		{
			Key:         "defaults.llm_provider",
			Value:       "openrouter",
			Description: "Default LLM provider for all pipeline stages",
		},
		{
			Key:         "defaults.debug_agents",
			Value:       false,
			Description: "Enable verbose debug logging for agent executions",
		},

		// ===================
		// Stage: process_book
		// ===================
		{
			Key:         "stages.process_book.label_threshold",
			Value:       20,
			Description: "Pages labeled before triggering book-level operations (metadata, ToC)",
		},
		{
			Key:         "stages.process_book.front_matter_pages",
			Value:       50,
			Description: "Number of pages from start to search for table of contents",
		},
		{
			Key:         "stages.process_book.consecutive_front_matter_required",
			Value:       50,
			Description: "Consecutive pages from page 1 that must be blend_complete before ToC search",
		},
		{
			Key:         "stages.process_book.max_book_op_retries",
			Value:       3,
			Description: "Maximum retries for book-level operations (metadata, ToC)",
		},
		{
			Key:         "stages.process_book.max_page_op_retries",
			Value:       3,
			Description: "Maximum retries for page-level operations (OCR, blend, label)",
		},

		// ===================
		// Stage: ocr_book
		// ===================
		{
			Key:         "stages.ocr_book.checkpoint_interval",
			Value:       100,
			Description: "Log progress every N pages during OCR",
		},
		{
			Key:         "stages.ocr_book.max_retries",
			Value:       3,
			Description: "Maximum retries for failed OCR page operations",
		},

		// ===================
		// Stage: label_book
		// ===================
		{
			Key:         "stages.label_book.max_retries",
			Value:       3,
			Description: "Maximum retries for failed label page operations",
		},

		// ===================
		// Stage: metadata_book
		// ===================
		{
			Key:         "stages.metadata_book.page_count",
			Value:       20,
			Description: "Number of front pages to analyze for metadata extraction",
		},
		{
			Key:         "stages.metadata_book.max_retries",
			Value:       3,
			Description: "Maximum retries for metadata extraction",
		},

		// ===================
		// Stage: toc_book
		// ===================
		{
			Key:         "stages.toc_book.max_retries",
			Value:       3,
			Description: "Maximum retries for ToC extraction agent",
		},

		// ===================
		// Stage: link_toc
		// ===================
		{
			Key:         "stages.link_toc.max_retries",
			Value:       3,
			Description: "Maximum retries for ToC linking agent",
		},

		// ===================
		// Stage: finalize_toc
		// ===================
		{
			Key:         "stages.finalize_toc.min_gap_size",
			Value:       15,
			Description: "Minimum pages between ToC entries to consider a gap significant",
		},
		{
			Key:         "stages.finalize_toc.max_retries",
			Value:       3,
			Description: "Maximum retries for gap validation agent",
		},

		// ===================
		// Stage: common_structure
		// ===================
		{
			Key:         "stages.common_structure.max_retries",
			Value:       3,
			Description: "Maximum retries for structure classification/polish",
		},

		// ===================
		// Scheduler
		// ===================
		{
			Key:         "scheduler.queue_size",
			Value:       10000,
			Description: "Size of work queue for provider and CPU pools",
		},
		{
			Key:         "scheduler.results_buffer",
			Value:       1000,
			Description: "Buffer size for results channel",
		},
		{
			Key:         "scheduler.cpu_workers",
			Value:       0,
			Description: "Number of CPU workers (0 = use runtime.NumCPU())",
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
// Returns ErrNoDefault if no default exists for the key.
func ResetToDefault(ctx context.Context, store Store, key string) error {
	def := GetDefault(key)
	if def == nil {
		return fmt.Errorf("%w for key %q", ErrNoDefault, key)
	}
	return store.Set(ctx, key, def.Value, def.Description)
}
