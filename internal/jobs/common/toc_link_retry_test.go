package common

import (
	"context"
	"testing"
)

func TestPersistTocEntryLinkStateIsDurable(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("TocEntry", "entry-1", map[string]any{})
	book := NewBookState("book-1")
	book.Store = store

	if err := PersistTocEntryLinkState(context.Background(), book, "entry-1", 2, false, "second rejection"); err != nil {
		t.Fatal(err)
	}
	doc := store.GetDoc("TocEntry", "entry-1")
	if doc["link_retries"] != 2 || doc["link_failed"] != false || doc["link_failure_reason"] != "second rejection" {
		t.Fatalf("retry state = %#v", doc)
	}
	if _, ok := doc["link_failed_at"]; ok {
		t.Fatalf("nonterminal retry has failed timestamp: %#v", doc)
	}

	if err := PersistTocEntryLinkState(context.Background(), book, "entry-1", 3, true, "budget exhausted"); err != nil {
		t.Fatal(err)
	}
	doc = store.GetDoc("TocEntry", "entry-1")
	if doc["link_retries"] != 3 || doc["link_failed"] != true || doc["link_failed_at"] == "" {
		t.Fatalf("terminal state = %#v", doc)
	}
}

func TestLoadTocEntriesKeepsDurableRetryAndOmitsTerminalFailure(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("TocEntry", "entry-pending", map[string]any{
		"_tocID":              "toc-1",
		"title":               "Pending chapter",
		"sort_order":          1,
		"link_retries":        2,
		"link_failed":         false,
		"link_failure_reason": "two attempts rejected",
	})
	store.SetDoc("TocEntry", "entry-failed", map[string]any{
		"_tocID":       "toc-1",
		"title":        "Unlinkable tail",
		"sort_order":   2,
		"link_retries": 3,
		"link_failed":  true,
	})

	entries, err := loadTocEntriesViaStore(context.Background(), store, "toc-1")
	if err != nil {
		t.Fatal(err)
	}
	if len(entries) != 1 || entries[0].DocID != "entry-pending" {
		t.Fatalf("pending entries = %#v", entries)
	}
	if entries[0].LinkRetries != 2 || entries[0].LinkFailureReason != "two attempts rejected" {
		t.Fatalf("durable retry metadata = %#v", entries[0])
	}
}
