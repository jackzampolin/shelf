package common

import (
	"context"
	"testing"
)

func TestQuarantineOCRPagesIsExplicitTerminalState(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 2
	book.OcrProviders = []string{"chandra-local"}
	for index, docID := range []string{"page-1", "page-2"} {
		pageNum := index + 1
		page := book.GetOrCreatePage(pageNum)
		page.SetPageDocID(docID)
		store.SetDoc("Page", page.GetPageDocID(), map[string]any{"ocr_complete": false})
	}
	book.GetPage(1).MarkOcrComplete("chandra-local", "good")

	pages, err := QuarantineOCRPages(context.Background(), book, []int{2}, "map loops at token limit")
	if err != nil {
		t.Fatal(err)
	}
	if len(pages) != 1 || pages[0] != 2 {
		t.Fatalf("pages = %v, want [2]", pages)
	}
	if !book.AllPagesOcrComplete() {
		t.Fatal("explicitly quarantined page should resolve the page pipeline")
	}
	if book.GetPage(2).OcrComplete("chandra-local") {
		t.Fatal("quarantine must not masquerade as successful OCR")
	}
	quarantined, reason := book.GetPage(2).OCRQuarantine()
	if !quarantined || reason != "map loops at token limit" {
		t.Fatalf("quarantine = (%v, %q)", quarantined, reason)
	}
	doc := store.GetDoc("Page", "page-2")
	if doc["ocr_quarantined"] != true || doc["ocr_quarantine_reason"] != reason || doc["ocr_complete"] != false {
		t.Fatalf("persisted page = %#v", doc)
	}
}

func TestRepairOCRPagesClearsQuarantine(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	book.OcrProviders = []string{"chandra-local"}
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")
	page.QuarantineOCR("old reason")
	store.SetDoc("Page", "page-1", map[string]any{
		"ocr_complete":          false,
		"ocr_quarantined":       true,
		"ocr_quarantine_reason": "old reason",
	})

	if _, err := RepairOCRPages(context.Background(), book, []int{1}, []string{"chandra-local"}); err != nil {
		t.Fatal(err)
	}
	if quarantined, _ := page.OCRQuarantine(); quarantined {
		t.Fatal("repair should make a quarantined page eligible for OCR again")
	}
	doc := store.GetDoc("Page", "page-1")
	if doc["ocr_quarantined"] != false {
		t.Fatalf("ocr_quarantined = %v, want false", doc["ocr_quarantined"])
	}
	if _, ok := doc["ocr_quarantine_reason"]; ok {
		t.Fatalf("ocr_quarantine_reason was not cleared: %#v", doc)
	}
}
