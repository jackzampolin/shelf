package common

import (
	"context"
	"strings"
	"testing"
)

func insertionBook() (*BookState, *MemoryStateStore) {
	book, store := tocEntryRepairBook()
	store.SetDoc("TocEntry", "entry-good", map[string]any{
		"_tocID": "toc-1", "title": "Before", "level": 3, "level_name": "section",
		"sort_order": 0, "_actual_pageID": "page-1", "source": "extracted",
	})
	store.SetDoc("TocEntry", "entry-failed", map[string]any{
		"_tocID": "toc-1", "title": "After", "level": 3, "level_name": "section",
		"sort_order": 2, "_actual_pageID": "page-3", "source": "extracted",
	})
	store.SetDoc("TocEntry", "entry-excluded", map[string]any{
		"_tocID": "toc-1", "title": "Duplicate OCR Fragment", "level": 3, "level_name": "section",
		"sort_order": 1, "link_excluded": true, "source": "extracted",
	})
	book.TotalPages = 3
	book.OcrProviders = []string{"ocr"}
	for pageNum := 1; pageNum <= 3; pageNum++ {
		page := book.GetOrCreatePage(pageNum)
		page.SetPageDocID("page-" + string(rune('0'+pageNum)))
		page.MarkOcrComplete("ocr", "resolved")
		store.SetDoc("Page", page.GetPageDocID(), map[string]any{"page_num": pageNum})
	}
	return book, store
}

func TestInsertTocEntryPreservesLinksAndSourceOrder(t *testing.T) {
	book, store := insertionBook()
	spec := TocEntryInsertionSpec{
		Title: "Missing Middle", PageNum: 2, Level: 3, LevelName: "section",
		AfterEntryDocID: "entry-good", Reason: "visible on original scan 2",
	}
	result, err := InsertTocEntry(context.Background(), book, spec)
	if err != nil {
		t.Fatal(err)
	}
	if result.EntryDocID == "" || result.PageNum != 2 || result.SortOrder != 1 {
		t.Fatalf("result = %#v", result)
	}
	inserted := store.GetDoc("TocEntry", result.EntryDocID)
	if inserted["_actual_pageID"] != "page-2" || inserted["source"] != "operator" {
		t.Fatalf("inserted entry = %#v", inserted)
	}
	if inserted["link_repair_reason"] != spec.Reason || inserted["link_repaired_at"] == "" {
		t.Fatalf("insertion provenance = %#v", inserted)
	}
	if store.GetDoc("TocEntry", "entry-good")["_actual_pageID"] != "page-1" || store.GetDoc("TocEntry", "entry-failed")["_actual_pageID"] != "page-3" {
		t.Fatal("insertion changed an existing page link")
	}
	if got := numericToInt(store.GetDoc("TocEntry", "entry-excluded")["sort_order"]); got != 2 {
		t.Fatalf("excluded sort order = %d, want 2", got)
	}
	if got := numericToInt(store.GetDoc("TocEntry", "entry-failed")["sort_order"]); got != 3 {
		t.Fatalf("following sort order = %d, want 3", got)
	}
	if !book.TocLinkIsDone() || book.TocFinalizeIsDone() || book.StructureIsDone() {
		t.Fatal("insertion did not preserve link completion and reset downstream stages")
	}
}

func TestInsertTocEntryIsIdempotentAfterDurableUpsert(t *testing.T) {
	book, store := insertionBook()
	spec := TocEntryInsertionSpec{Title: "Missing Middle", PageNum: 2, Level: 3, LevelName: "section", AfterEntryDocID: "entry-good", Reason: "source verified"}
	first, err := InsertTocEntry(context.Background(), book, spec)
	if err != nil {
		t.Fatal(err)
	}
	second, err := InsertTocEntry(context.Background(), book, spec)
	if err != nil {
		t.Fatal(err)
	}
	if first.EntryDocID != second.EntryDocID {
		t.Fatalf("replay created a new document: %s != %s", first.EntryDocID, second.EntryDocID)
	}
	store.mu.RLock()
	got := len(store.docs["TocEntry"])
	store.mu.RUnlock()
	if got != 4 {
		t.Fatalf("TocEntry count = %d, want 4", got)
	}
}

func TestValidateTocEntryInsertionRejectsUnsafeOrder(t *testing.T) {
	tests := []struct {
		name   string
		spec   TocEntryInsertionSpec
		mutate func(*MemoryStateStore)
		want   string
	}{
		{name: "missing reason", spec: TocEntryInsertionSpec{Title: "x", PageNum: 2, Level: 3, LevelName: "section", AfterEntryDocID: "entry-good"}, want: "reason is required"},
		{name: "before anchor", spec: TocEntryInsertionSpec{Title: "x", PageNum: 1, Level: 3, LevelName: "section", AfterEntryDocID: "entry-failed", Reason: "verified"}, want: "precedes anchor"},
		{name: "after next", spec: TocEntryInsertionSpec{Title: "x", PageNum: 3, Level: 3, LevelName: "section", AfterEntryDocID: "entry-good", Reason: "verified"}, mutate: func(store *MemoryStateStore) {
			store.SetDoc("TocEntry", "entry-failed", map[string]any{"_tocID": "toc-1", "title": "After", "level": 3, "level_name": "section", "sort_order": 2, "_actual_pageID": "page-2", "source": "extracted"})
		}, want: "follows next source entry"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			book, store := insertionBook()
			if tt.mutate != nil {
				tt.mutate(store)
			}
			err := ValidateTocEntryInsertion(context.Background(), book, tt.spec)
			if err == nil || !strings.Contains(err.Error(), tt.want) {
				t.Fatalf("error = %v, want substring %q", err, tt.want)
			}
		})
	}
}
