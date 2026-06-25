package server

import (
	"fmt"
	"log/slog"

	"github.com/jackzampolin/shelf/internal/providers"
)

// validateProviderRouting ensures every provider name the pipeline will route to
// is actually registered. Registration comes from YAML config while routing names
// come from the DefraDB settings store, so the two can drift.
func validateProviderRouting(registry *providers.Registry, llmNames, ocrNames []string) error {
	for _, name := range llmNames {
		if name == "" {
			continue
		}
		if !registry.HasLLM(name) {
			return fmt.Errorf("configured LLM provider %q is not registered (check llm_providers and defaults.llm_provider)", name)
		}
	}
	for _, name := range ocrNames {
		if name == "" {
			continue
		}
		if !registry.HasOCR(name) {
			return fmt.Errorf("configured OCR provider %q is not registered (check ocr_providers and defaults.ocr_providers)", name)
		}
	}
	return nil
}

func validateProviderRoutingForStartup(logger *slog.Logger, registry *providers.Registry, llmNames, ocrNames []string, failFast bool) error {
	err := validateProviderRouting(registry, llmNames, ocrNames)
	if err == nil {
		return nil
	}
	if failFast {
		return err
	}
	if logger != nil {
		logger.Warn("provider routing validation failed", "error", err)
	}
	return nil
}

// dedupeNonEmpty returns the distinct non-empty values in input order.
func dedupeNonEmpty(values ...string) []string {
	seen := make(map[string]bool)
	var out []string
	for _, v := range values {
		if v == "" || seen[v] {
			continue
		}
		seen[v] = true
		out = append(out, v)
	}
	return out
}
