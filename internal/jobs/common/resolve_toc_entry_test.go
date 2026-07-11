package common

import (
	"context"
	"strings"
	"testing"
)

func resolvableTocEntryBook() (*BookState, *MemoryStateStore) {
	book, store := tocEntryRepairBook()
	book.TotalPages = 2
	book.OcrProviders = []string{"ocr"}
	for pageNum := 1; pageNum <= 2; pageNum++ {
		page := book.GetOrCreatePage(pageNum)
		page.SetPageDocID("page-" + string(rune('0'+pageNum)))
		page.MarkOcrComplete("ocr", "resolved")
		store.SetDoc("Page", page.GetPageDocID(), map[string]any{"page_num": pageNum})
	}
	return book, store
}

func TestResolveTocEntryLinksOnlyTargetAndReopensStage(t *testing.T) {
	book, store := resolvableTocEntryBook()
	result, err := ResolveTocEntry(context.Background(), book, "entry-failed", 2, "verified title on scan page 2", false, "Corrected title")
	if err != nil {
		t.Fatal(err)
	}
	if result.PageNum != 2 || result.PendingCount != 0 || result.CID == "" {
		t.Fatalf("result = %#v", result)
	}
	failed := store.GetDoc("TocEntry", "entry-failed")
	if failed["_actual_pageID"] != "page-2" || failed["link_failed"] != false {
		t.Fatalf("resolved entry = %#v", failed)
	}
	if failed["title"] != "Corrected title" || result.Title != "Corrected title" {
		t.Fatalf("title override result=%#v entry=%#v", result, failed)
	}
	if failed["link_repair_reason"] != "verified title on scan page 2" || failed["link_repaired_at"] == "" {
		t.Fatalf("resolution provenance = %#v", failed)
	}
	good := store.GetDoc("TocEntry", "entry-good")
	if good["_actual_pageID"] != "page-10" {
		t.Fatalf("known-good link was changed: %#v", good)
	}
	linkState := book.GetTocLinkState()
	if !linkState.IsComplete() {
		t.Fatalf("link state = %#v, want complete", linkState)
	}
}

func TestResolveTocEntryRejectsUnsafePage(t *testing.T) {
	tests := []struct {
		name   string
		page   int
		mutate func(*BookState)
		want   string
	}{
		{name: "range", page: 3, want: "outside valid range"},
		{name: "quarantined", page: 1, mutate: func(book *BookState) { book.GetPage(1).QuarantineOCR("bad scan") }, want: "OCR-quarantined"},
		{name: "unresolved", page: 1, mutate: func(book *BookState) { book.GetPage(1).ResetOcrProviders([]string{"ocr"}) }, want: "terminal OCR"},
		{name: "missing doc id", page: 1, mutate: func(book *BookState) { book.GetPage(1).SetPageDocID("") }, want: "durable document ID"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			book, _ := resolvableTocEntryBook()
			if tt.mutate != nil {
				tt.mutate(book)
			}
			_, err := ResolveTocEntry(context.Background(), book, "entry-failed", tt.page, "source-backed reason", false, "")
			if err == nil || !strings.Contains(err.Error(), tt.want) {
				t.Fatalf("error = %v, want substring %q", err, tt.want)
			}
		})
	}
}

func TestResolveTocEntryRequiresExplicitRelink(t *testing.T) {
	book, store := resolvableTocEntryBook()
	if _, err := ResolveTocEntry(context.Background(), book, "entry-good", 2, "verified correction", false, ""); err == nil || !strings.Contains(err.Error(), "already linked") {
		t.Fatalf("ordinary resolution error = %v, want already linked refusal", err)
	}
	result, err := ResolveTocEntry(context.Background(), book, "entry-good", 2, "verified correction", true, "")
	if err != nil {
		t.Fatal(err)
	}
	if result.PageNum != 2 || store.GetDoc("TocEntry", "entry-good")["_actual_pageID"] != "page-2" {
		t.Fatalf("relink result = %#v entry=%#v", result, store.GetDoc("TocEntry", "entry-good"))
	}
}

func TestResolveTocEntriesAppliesCohortAndReloadsOnce(t *testing.T) {
	book, store := resolvableTocEntryBook()
	store.SetDoc("TocEntry", "entry-failed-2", map[string]any{
		"_tocID":              "toc-1",
		"title":               "Second Broken Heading",
		"sort_order":          3,
		"link_retries":        3,
		"link_failed":         true,
		"link_failure_reason": "budget exhausted",
	})

	results, pending, err := ResolveTocEntries(context.Background(), book, []TocEntryResolutionSpec{
		{EntryDocID: "entry-failed", PageNum: 1, Reason: "verified first heading"},
		{EntryDocID: "entry-failed-2", PageNum: 2, Title: "Corrected second heading", Reason: "verified second heading"},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(results) != 2 || pending != 0 || results[0].PendingCount != 0 || results[1].PendingCount != 0 {
		t.Fatalf("results=%#v pending=%d", results, pending)
	}
	if got := store.GetDoc("TocEntry", "entry-failed")["_actual_pageID"]; got != "page-1" {
		t.Fatalf("first page link = %#v", got)
	}
	second := store.GetDoc("TocEntry", "entry-failed-2")
	if second["_actual_pageID"] != "page-2" || second["title"] != "Corrected second heading" {
		t.Fatalf("second resolution = %#v", second)
	}
	if got := store.GetDoc("TocEntry", "entry-good")["_actual_pageID"]; got != "page-10" {
		t.Fatalf("known-good link changed: %#v", got)
	}
}

func TestResolveTocEntriesRejectsDuplicateBeforeMutation(t *testing.T) {
	book, store := resolvableTocEntryBook()
	_, _, err := ResolveTocEntries(context.Background(), book, []TocEntryResolutionSpec{
		{EntryDocID: "entry-failed", PageNum: 1, Reason: "first"},
		{EntryDocID: "entry-failed", PageNum: 2, Reason: "duplicate"},
	})
	if err == nil || !strings.Contains(err.Error(), "duplicate ToC entry") {
		t.Fatalf("error = %v, want duplicate refusal", err)
	}
	if got := store.GetDoc("TocEntry", "entry-failed")["_actual_pageID"]; got != nil {
		t.Fatalf("duplicate batch mutated target: %#v", got)
	}
}
