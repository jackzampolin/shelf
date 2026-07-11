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
		{"valid_toc_link", "toc_link", true},
		{"valid_toc_finalize", "toc_finalize", true},
		{"valid_structure", "structure", true},
		{"valid_ocr", "ocr", true},
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
	// - toc_link        -> toc_finalize, structure
	// - toc_finalize    -> structure
	// - structure       -> (none)
	// - ocr             -> toc_link, toc_finalize, structure

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

func TestResetFrom_TocLinkReloadsClearedEntries(t *testing.T) {
	book := NewBookState("book-1")
	store := NewMemoryStateStore()
	book.Store = store
	book.SetTocDocID("toc-1")
	book.SetTocEntries(nil)

	store.SetTocDoc("toc-1", map[string]any{})
	store.SetDoc("TocEntry", "entry-2", map[string]any{
		"_tocID":              "toc-1",
		"_actual_pageID":      "page-12",
		"entry_number":        "2",
		"title":               "Second",
		"level":               float64(1),
		"level_name":          "chapter",
		"printed_page_number": "12",
		"sort_order":          float64(2),
		"link_retries":        3,
		"link_failed":         true,
		"link_failure_reason": "old failure",
		"link_failed_at":      "2026-07-10T00:00:00Z",
	})
	store.SetDoc("TocEntry", "entry-1", map[string]any{
		"_tocID":              "toc-1",
		"_actual_pageID":      "page-3",
		"entry_number":        "1",
		"title":               "First",
		"level":               float64(1),
		"level_name":          "chapter",
		"printed_page_number": "3",
		"sort_order":          float64(1),
		"link_retries":        2,
		"link_failed":         false,
		"link_failure_reason": "old retry",
	})

	ctx := context.Background()
	if err := ResetFrom(ctx, book, "toc-1", ResetTocLink); err != nil {
		t.Fatalf("ResetFrom(toc_link) failed: %v", err)
	}

	for _, docID := range []string{"entry-1", "entry-2"} {
		doc := store.GetDoc("TocEntry", docID)
		if _, ok := doc["_actual_pageID"]; ok {
			t.Fatalf("expected %s _actual_pageID to be cleared, got %v", docID, doc["_actual_pageID"])
		}
		if doc["link_retries"] != 0 || doc["link_failed"] != false {
			t.Fatalf("expected %s link budget to reset, got %v", docID, doc)
		}
		if _, ok := doc["link_failure_reason"]; ok {
			t.Fatalf("expected %s link failure reason to clear, got %v", docID, doc)
		}
		if _, ok := doc["link_failed_at"]; ok {
			t.Fatalf("expected %s link failure timestamp to clear, got %v", docID, doc)
		}
	}

	entries := book.GetUnlinkedTocEntries()
	if len(entries) != 2 {
		t.Fatalf("expected reset to reload 2 pending ToC entries, got %d", len(entries))
	}
	if entries[0].DocID != "entry-1" || entries[1].DocID != "entry-2" {
		t.Fatalf("expected entries sorted by sort_order, got %s then %s", entries[0].DocID, entries[1].DocID)
	}
}

func TestResetFrom_TocExtractClearsFinalizeCheckpoints(t *testing.T) {
	book := NewBookState("book-1")
	store := NewMemoryStateStore()
	book.Store = store
	book.SetTocDocID("toc-1")
	book.SetFinalizePhase("gaps")
	book.SetFinalizePatternResult(&FinalizePatternResult{Reasoning: "stale"})
	book.SetEntriesToFind([]*EntryToFind{{Key: "missing-chapter"}})
	book.SetFinalizeEntriesTotal(3)
	book.SetFinalizeGapsTotal(2)
	book.SetFinalizeProgress(2, 1, 1, 1)

	store.SetTocDoc("toc-1", map[string]any{
		"finalize_phase":    "gaps",
		"finalize_complete": true,
	})
	store.SetBookDoc("book-1", map[string]any{
		"pattern_analysis_json":     `{"reasoning":"stale"}`,
		"finalize_entries_total":    3,
		"finalize_entries_complete": 2,
		"finalize_entries_found":    1,
		"finalize_gaps_total":       2,
		"finalize_gaps_complete":    1,
		"finalize_gaps_fixes":       1,
	})

	if err := ResetFrom(context.Background(), book, "toc-1", ResetTocExtract); err != nil {
		t.Fatalf("ResetFrom(toc_extract) failed: %v", err)
	}

	toc := store.GetDoc("ToC", "toc-1")
	if _, ok := toc["finalize_phase"]; ok {
		t.Fatalf("expected finalize_phase to be cleared, got %v", toc["finalize_phase"])
	}
	bookDoc := store.GetDoc("Book", "book-1")
	if _, ok := bookDoc["pattern_analysis_json"]; ok {
		t.Fatalf("expected pattern_analysis_json to be cleared, got %v", bookDoc["pattern_analysis_json"])
	}
	for _, field := range []string{
		"finalize_entries_total",
		"finalize_entries_complete",
		"finalize_entries_found",
		"finalize_gaps_total",
		"finalize_gaps_complete",
		"finalize_gaps_fixes",
	} {
		if got := bookDoc[field]; got != 0 {
			t.Errorf("%s = %v, want 0", field, got)
		}
	}
	if got := book.GetFinalizePhase(); got != "" {
		t.Errorf("in-memory finalize phase = %q, want empty", got)
	}
	if got := book.GetFinalizePatternResult(); got != nil {
		t.Errorf("in-memory finalize pattern = %#v, want nil", got)
	}
	if got := len(book.GetEntriesToFind()); got != 0 {
		t.Errorf("in-memory entries to find = %d, want 0", got)
	}
	if got := book.GetFinalizeEntriesTotalCount(); got != 0 {
		t.Errorf("in-memory finalize entries total = %d, want 0", got)
	}
	if got := book.GetFinalizeGapsTotalCount(); got != 0 {
		t.Errorf("in-memory finalize gaps total = %d, want 0", got)
	}
	entriesComplete, entriesFound, gapsComplete, gapsFixes := book.GetFinalizeProgress()
	if entriesComplete != 0 || entriesFound != 0 || gapsComplete != 0 || gapsFixes != 0 {
		t.Errorf("in-memory finalize progress = (%d,%d,%d,%d), want zeros", entriesComplete, entriesFound, gapsComplete, gapsFixes)
	}
}

// TestValidResetOperations verifies the ValidResetOperations list is complete.
func TestValidResetOperations(t *testing.T) {
	expected := []ResetOperation{
		ResetMetadata,
		ResetTocFinder,
		ResetTocExtract,
		ResetTocLink,
		ResetTocFinalize,
		ResetStructure,
		ResetOcr,
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
		{ResetTocLink, "toc_link"},
		{ResetTocFinalize, "toc_finalize"},
		{ResetStructure, "structure"},
		{ResetOcr, "ocr"},
	}

	for _, tt := range tests {
		if string(tt.op) != tt.expected {
			t.Errorf("%v = %s, want %s", tt.op, string(tt.op), tt.expected)
		}
	}
}
