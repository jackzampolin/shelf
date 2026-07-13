package common

import (
	"context"
	"strings"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
)

func tocEntryRepairBook() (*BookState, *MemoryStateStore) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{
		"structure_complete":     true,
		"toc_link_entries_total": 2,
		"toc_link_entries_done":  2,
	})
	store.SetDoc("ToC", "toc-1", map[string]any{
		"link_complete":     true,
		"finalize_complete": true,
	})
	store.SetDoc("TocEntry", "entry-good", map[string]any{
		"_tocID":         "toc-1",
		"title":          "Chapter One",
		"sort_order":     1,
		"_actual_pageID": "page-10",
		"link_retries":   0,
		"link_failed":    false,
	})
	store.SetDoc("TocEntry", "entry-failed", map[string]any{
		"_tocID":              "toc-1",
		"title":               "A Rite of Succession",
		"sort_order":          2,
		"link_retries":        3,
		"link_failed":         true,
		"link_failure_reason": "budget exhausted",
		"link_failed_at":      "2026-07-10T00:00:00Z",
	})
	store.SetDoc("AgentState", "agent-failed", map[string]any{
		"_bookID":      "book-1",
		"agent_type":   AgentTypeTocEntryFinder,
		"entry_doc_id": "entry-failed",
	})

	book := NewBookState("book-1")
	book.Store = store
	book.SetTocDocID("toc-1")
	book.SetOpState(OpTocExtract, false, true, false, 0)
	book.SetOpState(OpTocLink, false, true, false, 0)
	book.SetOpState(OpTocFinalize, false, true, false, 0)
	book.SetOpState(OpStructure, false, true, false, 0)
	book.SetTocEntries([]*toc_entry_finder.TocEntry{})
	book.SetAgentState(&AgentState{
		DocID:      "agent-failed",
		AgentID:    "old-agent",
		AgentType:  AgentTypeTocEntryFinder,
		EntryDocID: "entry-failed",
	})
	return book, store
}

func TestRepairTocEntryPreservesSuccessfulLinksAndReopensOnlyPendingEntry(t *testing.T) {
	book, store := tocEntryRepairBook()
	result, err := RepairTocEntry(context.Background(), book, "entry-failed", "retry after durable budget fix")
	if err != nil {
		t.Fatal(err)
	}
	if result.EntryDocID != "entry-failed" || result.Title != "A Rite of Succession" || result.SortOrder != 2 || result.CID == "" {
		t.Fatalf("unexpected result: %#v", result)
	}

	good := store.GetDoc("TocEntry", "entry-good")
	if good["_actual_pageID"] != "page-10" {
		t.Fatalf("successful link was changed: %#v", good)
	}
	failed := store.GetDoc("TocEntry", "entry-failed")
	if failed["link_retries"] != 0 || failed["link_failed"] != false {
		t.Fatalf("entry retry state was not reset: %#v", failed)
	}
	if _, ok := failed["link_failure_reason"]; ok {
		t.Fatalf("entry failure reason survived: %#v", failed)
	}
	if failed["link_repair_reason"] != "retry after durable budget fix" || failed["link_repaired_at"] == "" {
		t.Fatalf("repair provenance missing: %#v", failed)
	}
	if store.GetDoc("AgentState", "agent-failed") != nil || book.GetAgentState(AgentTypeTocEntryFinder, "entry-failed") != nil {
		t.Fatal("stale per-entry agent state survived repair")
	}
	if book.TocLinkIsDone() || book.TocFinalizeIsDone() || book.StructureIsDone() {
		t.Fatal("link or downstream stages were not reopened")
	}
	pending := book.GetTocEntries()
	if len(pending) != 1 || pending[0].DocID != "entry-failed" || pending[0].LinkRetries != 0 {
		t.Fatalf("pending entries = %#v, want repaired entry only", pending)
	}
	if total, done := book.GetTocLinkProgress(); total != 1 || done != 0 {
		t.Fatalf("link progress = %d/%d, want 0/1", done, total)
	}
}

func TestValidateTocEntryRepairRejectsUnsafeTargets(t *testing.T) {
	tests := []struct {
		name    string
		entryID string
		reason  string
		want    string
	}{
		{name: "missing reason", entryID: "entry-failed", reason: " ", want: "reason is required"},
		{name: "wrong toc", entryID: "entry-other", reason: "retry", want: "was not found"},
		{name: "linked", entryID: "entry-good", reason: "retry", want: "already linked"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			book, store := tocEntryRepairBook()
			store.SetDoc("TocEntry", "entry-other", map[string]any{"_tocID": "toc-other"})
			_, err := ValidateTocEntryRepair(context.Background(), book, tt.entryID, tt.reason)
			if err == nil || !strings.Contains(err.Error(), tt.want) {
				t.Fatalf("error = %v, want substring %q", err, tt.want)
			}
		})
	}
}
