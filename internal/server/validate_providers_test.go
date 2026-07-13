package server

import (
	"io"
	"log/slog"
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

func TestValidateProviderRoutingForStartup(t *testing.T) {
	reg := providers.NewRegistry()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	t.Run("warn mode does not fail startup", func(t *testing.T) {
		if err := validateProviderRoutingForStartup(logger, reg, []string{"missing-llm"}, []string{"missing-ocr"}, false); err != nil {
			t.Fatalf("warn mode should not return error, got %v", err)
		}
	})

	t.Run("strict mode fails startup", func(t *testing.T) {
		if err := validateProviderRoutingForStartup(logger, reg, []string{"missing-llm"}, nil, true); err == nil {
			t.Fatal("strict mode should return an error")
		}
	})
}
