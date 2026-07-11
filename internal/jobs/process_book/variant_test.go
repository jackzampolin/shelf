package process_book

import "testing"

func TestApplyVariantRecordsExecutionPlan(t *testing.T) {
	var cfg Config
	cfg.ApplyVariant(VariantOCROnly)

	if cfg.Variant != VariantOCROnly {
		t.Fatalf("Variant = %q, want %q", cfg.Variant, VariantOCROnly)
	}
	if !cfg.EnableOCR || cfg.EnableMetadata || cfg.EnableTocFinder || cfg.EnableTocExtract ||
		cfg.EnableTocLink || cfg.EnableTocFinalize || cfg.EnableStructure {
		t.Fatalf("ocr-only stage flags = %#v", cfg)
	}
}

func TestApplyInvalidVariantUsesStandard(t *testing.T) {
	var cfg Config
	cfg.ApplyVariant(PipelineVariant("bogus"))

	if cfg.Variant != VariantStandard {
		t.Fatalf("Variant = %q, want %q", cfg.Variant, VariantStandard)
	}
	if !cfg.EnableOCR || !cfg.EnableMetadata || !cfg.EnableTocFinder || !cfg.EnableTocExtract ||
		!cfg.EnableTocLink || !cfg.EnableTocFinalize || !cfg.EnableStructure {
		t.Fatalf("standard stage flags = %#v", cfg)
	}
}
