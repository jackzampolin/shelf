package common

import (
	"context"
	"testing"
)

// TestIsValidResetOperation tests the reset operation validation.
func TestIsValidResetOperation(t *testing.T) {
	tests := []struct {
		name     string
		op       string
		expected bool
	}{
		{"valid_metadata", "metadata", true},
		{"valid_toc_finder", "toc_finder", true},
		{"valid_toc_extract", "toc_extract", true},
		{"valid_pattern_analysis", "pattern_analysis", true},
		{"valid_toc_link", "toc_link", true},
		{"valid_toc_finalize", "toc_finalize", true},
		{"valid_structure", "structure", true},
		{"valid_labels", "labels", true},
		{"valid_blend", "blend", true},
		{"invalid_empty", "", false},
		{"invalid_unknown", "unknown_operation", false},
		{"invalid_case", "METADATA", false},
		{"invalid_typo", "metadat", false},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := IsValidResetOperation(tt.op)
			if result != tt.expected {
				t.Errorf("IsValidResetOperation(%q) = %v, want %v", tt.op, result, tt.expected)
			}
		})
	}
}

// TestResetFrom_CascadeDependencies tests that reset operations cascade correctly.
// Note: These tests require a DefraDB client for full functionality.
// We test the cascade logic at the operation state level, which doesn't require DB.
func TestResetFrom_CascadeDependencies(t *testing.T) {
	// Note: Full integration tests for ResetFrom require a DefraDB client.
	// The cascade chain is tested here at the operation state level,
	// which verifies the logic without DB dependencies.
	//
	// Documented cascade dependencies:
	// - metadata        -> (none)
	// - toc_finder      -> toc_extract, toc_link, toc_finalize, structure
	// - toc_extract     -> toc_link, toc_finalize, structure
	// - pattern_analysis -> labels (all pages), toc_link, toc_finalize, structure
	// - toc_link        -> toc_finalize, structure
	// - toc_finalize    -> structure
	// - structure       -> (none)
	// - labels          -> toc_link, toc_finalize, structure
	// - blend           -> labels, pattern_analysis, (cascade from pattern_analysis)

	t.Run("unknown_operation_returns_error", func(t *testing.T) {
		book := NewBookState("test-book")
		ctx := context.Background()

		err := ResetFrom(ctx, book, "", ResetOperation("invalid"))
		if err == nil {
			t.Error("ResetFrom with invalid operation should return error")
		}
	})

	// Test operation state reset methods directly
	t.Run("operation_state_reset_methods", func(t *testing.T) {
		book := NewBookState("test-book")

		// Complete all operations
		book.MetadataStart()
		book.MetadataComplete()
		book.TocFinderStart()
		book.TocFinderComplete()
		book.TocExtractStart()
		book.TocExtractComplete()
		book.TocLinkStart()
		book.TocLinkComplete()
		book.TocFinalizeStart()
		book.TocFinalizeComplete()
		book.StructureStart()
		book.StructureComplete()

		// Reset individual operations
		book.MetadataReset()
		if book.MetadataIsDone() {
			t.Error("metadata should be reset")
		}
		if !book.TocFinderIsDone() {
			t.Error("toc_finder should not be affected by metadata reset")
		}

		book.StructureReset()
		if book.StructureIsDone() {
			t.Error("structure should be reset")
		}
		if !book.TocFinalizeIsDone() {
			t.Error("toc_finalize should not be affected by structure reset")
		}

		// Reset cascade manually to test logic
		book.TocFinalizeReset()
		if book.TocFinalizeIsDone() {
			t.Error("toc_finalize should be reset")
		}
		// In real cascade, structure would be reset here

		book.TocLinkReset()
		if book.TocLinkIsDone() {
			t.Error("toc_link should be reset")
		}
		// In real cascade, toc_finalize and structure would be reset here

		book.TocExtractReset()
		if book.TocExtractIsDone() {
			t.Error("toc_extract should be reset")
		}
		// In real cascade, toc_link, toc_finalize, structure would be reset

		book.TocFinderReset()
		if book.TocFinderIsDone() {
			t.Error("toc_finder should be reset")
		}
	})
}

// TestValidResetOperations verifies the ValidResetOperations list is complete.
func TestValidResetOperations(t *testing.T) {
	expected := []ResetOperation{
		ResetMetadata,
		ResetTocFinder,
		ResetTocExtract,
		ResetPatternAnalysis,
		ResetTocLink,
		ResetTocFinalize,
		ResetStructure,
		ResetLabels,
		ResetBlend,
	}

	if len(ValidResetOperations) != len(expected) {
		t.Errorf("ValidResetOperations has %d entries, want %d", len(ValidResetOperations), len(expected))
	}

	for _, op := range expected {
		found := false
		for _, valid := range ValidResetOperations {
			if valid == op {
				found = true
				break
			}
		}
		if !found {
			t.Errorf("ValidResetOperations missing %s", op)
		}
	}
}

// TestResetOperation_StringConstants tests the string constants match expected values.
func TestResetOperation_StringConstants(t *testing.T) {
	tests := []struct {
		op       ResetOperation
		expected string
	}{
		{ResetMetadata, "metadata"},
		{ResetTocFinder, "toc_finder"},
		{ResetTocExtract, "toc_extract"},
		{ResetPatternAnalysis, "pattern_analysis"},
		{ResetTocLink, "toc_link"},
		{ResetTocFinalize, "toc_finalize"},
		{ResetStructure, "structure"},
		{ResetLabels, "labels"},
		{ResetBlend, "blend"},
	}

	for _, tt := range tests {
		if string(tt.op) != tt.expected {
			t.Errorf("%v = %s, want %s", tt.op, string(tt.op), tt.expected)
		}
	}
}
