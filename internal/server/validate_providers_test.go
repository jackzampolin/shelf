package server

import (
	"testing"

	"github.com/jackzampolin/shelf/internal/providers"
)

func TestValidateProviderRouting(t *testing.T) {
	reg := providers.NewRegistry()
	reg.RegisterLLM("local-llm", providers.NewMockClient())
	reg.RegisterOCR("local-ocr", providers.NewMockOCRProvider())

	t.Run("all registered", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"local-llm"}, []string{"local-ocr"}); err != nil {
			t.Fatalf("unexpected error: %v", err)
		}
	})
	t.Run("missing llm", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"nope"}, []string{"local-ocr"}); err == nil {
			t.Fatal("expected error for unregistered LLM provider")
		}
	})
	t.Run("missing ocr", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"local-llm"}, []string{"nope"}); err == nil {
			t.Fatal("expected error for unregistered OCR provider")
		}
	})
	t.Run("empty names skipped", func(t *testing.T) {
		if err := validateProviderRouting(reg, []string{"local-llm", ""}, nil); err != nil {
			t.Fatalf("empty names should be ignored, got %v", err)
		}
	})
}

func TestDedupeNonEmpty(t *testing.T) {
	got := dedupeNonEmpty("a", "", "a", "b")
	if len(got) != 2 || got[0] != "a" || got[1] != "b" {
		t.Fatalf("dedupeNonEmpty = %v, want [a b]", got)
	}
}
