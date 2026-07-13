package common

import (
	"context"
	"strings"
	"testing"
)

func TestExcludeTocEntryIsExplicitTerminalResolution(t *testing.T) {
	book, store := tocEntryRepairBook()
	result, err := ExcludeTocEntry(context.Background(), book, "entry-failed", "front-matter item is absent from the source PDF", false)
	if err != nil {
		t.Fatal(err)
	}
	if result.PendingCount != 0 || result.CID == "" {
		t.Fatalf("result = %#v", result)
	}
	entry := store.GetDoc("TocEntry", "entry-failed")
	if entry["link_excluded"] != true || entry["link_failed"] != false {
		t.Fatalf("excluded entry = %#v", entry)
	}
	if entry["link_exclusion_reason"] != "front-matter item is absent from the source PDF" || entry["link_excluded_at"] == "" {
		t.Fatalf("exclusion provenance = %#v", entry)
	}
	state := book.GetTocLinkState()
	if !state.IsComplete() {
		t.Fatalf("link state = %#v, want complete", state)
	}
}

func TestExcludeTocEntryRefusesLinkedOrUnexplainedTarget(t *testing.T) {
	book, _ := tocEntryRepairBook()
	if _, err := ExcludeTocEntry(context.Background(), book, "entry-good", "not needed", false); err == nil || !strings.Contains(err.Error(), "already linked") {
		t.Fatalf("linked exclusion error = %v", err)
	}
	if _, err := ExcludeTocEntry(context.Background(), book, "entry-failed", " ", false); err == nil || !strings.Contains(err.Error(), "reason is required") {
		t.Fatalf("empty reason error = %v", err)
	}
}

func TestExcludeTocEntryRequiresExplicitLinkedOverride(t *testing.T) {
	book, store := tocEntryRepairBook()
	result, err := ExcludeTocEntry(context.Background(), book, "entry-good", "duplicate of source entry", true)
	if err != nil {
		t.Fatal(err)
	}
	entry := store.GetDoc("TocEntry", "entry-good")
	if entry["link_excluded"] != true {
		t.Fatalf("entry = %#v, want explicit exclusion", entry)
	}
	if linked, ok := entry["_actual_pageID"]; ok && linked != nil && linked != "" {
		t.Fatalf("linked exclusion retained page link: %#v result=%#v", entry, result)
	}
}
