package common

import (
	"context"
	"strings"
	"testing"
)

func tocRangeRepairBook() (*BookState, *MemoryStateStore) {
	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 4
	book.OcrProviders = []string{"ocr"}
	book.SetTocDocID("toc-1")
	for pageNum := 1; pageNum <= book.TotalPages; pageNum++ {
		page := book.GetOrCreatePage(pageNum)
		page.MarkOcrComplete("ocr", "page text")
		page.SetOCRComplete(true)
		page.SetOcrMarkdown("page text")
	}
	store.SetBookDoc("book-1", map[string]any{})
	store.SetTocDoc("toc-1", map[string]any{
		"finder_failed":    true,
		"finder_retries":   3,
		"extract_complete": true,
		"link_complete":    true,
	})
	store.SetDoc("TocEntry", "entry-1", map[string]any{"_tocID": "toc-1"})
	return book, store
}

func TestRepairTocRangePersistsOverrideAndClearsDownstream(t *testing.T) {
	book, store := tocRangeRepairBook()
	result, err := RepairTocRange(context.Background(), book, 2, 3, "verified against printed contents")
	if err != nil {
		t.Fatal(err)
	}
	if result.TocDocID != "toc-1" || result.StartPage != 2 || result.EndPage != 3 || result.CID == "" {
		t.Fatalf("unexpected result: %#v", result)
	}
	if !book.TocFinderIsComplete() || !book.GetTocFound() {
		t.Fatal("finder override was not reflected in memory")
	}
	if start, end := book.GetTocPageRange(); start != 2 || end != 3 {
		t.Fatalf("in-memory range = %d-%d, want 2-3", start, end)
	}
	if book.TocExtractIsDone() || book.TocLinkIsDone() || book.TocFinalizeIsDone() || book.StructureIsDone() {
		t.Fatal("downstream operations were not reset")
	}
	if got := store.GetDoc("TocEntry", "entry-1"); got != nil {
		t.Fatalf("stale ToC entry survived: %v", got)
	}
	toc := store.GetDoc("ToC", "toc-1")
	if toc["toc_found"] != true || toc["finder_complete"] != true || toc["finder_failed"] != false || toc["finder_retries"] != 0 {
		t.Fatalf("finder state = %v", toc)
	}
	if toc["start_page"] != 2 || toc["end_page"] != 3 || toc["finder_override"] != true {
		t.Fatalf("override range/provenance = %v", toc)
	}
	if toc["finder_override_reason"] != "verified against printed contents" || toc["finder_override_at"] == "" {
		t.Fatalf("override provenance = %v", toc)
	}
}

func TestValidateTocRangeRepairRejectsUnsafeRanges(t *testing.T) {
	tests := []struct {
		name   string
		mutate func(*BookState)
		start  int
		end    int
		reason string
		want   string
	}{
		{name: "bounds", start: 0, end: 2, reason: "source", want: "outside valid range"},
		{name: "reason", start: 1, end: 2, reason: " ", want: "reason is required"},
		{name: "missing page", mutate: func(book *BookState) { delete(book.Pages, 2) }, start: 1, end: 2, reason: "source", want: "page 2 is missing"},
		{name: "quarantine", mutate: func(book *BookState) { book.GetPage(2).QuarantineOCR("blank map") }, start: 1, end: 2, reason: "source", want: "OCR-quarantined"},
		{name: "unresolved", mutate: func(book *BookState) { book.GetPage(2).ResetOcrProviders([]string{"ocr"}) }, start: 1, end: 2, reason: "source", want: "terminal OCR"},
		{name: "empty text", mutate: func(book *BookState) { book.GetPage(2).SetOcrMarkdown(" ") }, start: 1, end: 2, reason: "source", want: "no OCR text"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			book, _ := tocRangeRepairBook()
			if tt.mutate != nil {
				tt.mutate(book)
			}
			err := ValidateTocRangeRepair(context.Background(), book, tt.start, tt.end, tt.reason)
			if err == nil || !strings.Contains(err.Error(), tt.want) {
				t.Fatalf("error = %v, want substring %q", err, tt.want)
			}
		})
	}
}
