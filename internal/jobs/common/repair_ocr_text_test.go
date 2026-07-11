package common

import (
	"context"
	"testing"
)

func TestRepairOCRTextPagePersistsVerifiedTextAndReason(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	book.OcrProviders = []string{"chandra-local"}
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")
	page.QuarantineOCR("model output truncated")
	store.SetDoc("Page", "page-1", map[string]any{
		"ocr_complete":          false,
		"ocr_quarantined":       true,
		"ocr_quarantine_reason": "model output truncated",
	})
	store.SetDoc("OcrResult", "partial", map[string]any{
		"_pageID": "page-1", "provider": "chandra-local", "text": "partial",
	})

	text := "# Source map\n\n[Full-page map; title and legend transcribed.]"
	reason := "Verified against source PDF page 1"
	result, err := RepairOCRTextPage(context.Background(), book, 1, text, reason)
	if err != nil {
		t.Fatal(err)
	}
	if result.Page != 1 || result.Characters != len(text) || result.DeletedResults != 1 {
		t.Fatalf("result = %#v", result)
	}
	if store.GetDoc("OcrResult", "partial") != nil {
		t.Fatal("prior OCR result was not deleted")
	}
	repair := store.GetDoc("OcrResult", "auto-OcrResult-1")
	if repair["provider"] != OperatorVerifiedOCRProvider || repair["text"] != text {
		t.Fatalf("verified result = %#v", repair)
	}
	metadata, ok := repair["provider_metadata"].(map[string]any)
	if !ok || metadata["reason"] != reason {
		t.Fatalf("verified metadata = %#v", repair["provider_metadata"])
	}
	doc := store.GetDoc("Page", "page-1")
	if doc["ocr_complete"] != true || doc["ocr_quarantined"] != false || doc["ocr_markdown"] != text {
		t.Fatalf("page doc = %#v", doc)
	}
	if !page.IsOCRComplete() || !page.OcrResolved(book.OcrProviders) {
		t.Fatal("verified repair did not resolve in-memory page")
	}
}

func TestRepairOCRTextPageValidatesBeforeWrites(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")

	for _, test := range []struct {
		text   string
		reason string
	}{
		{"", "verified blank"},
		{"explicit text", ""},
	} {
		if _, err := RepairOCRTextPage(context.Background(), book, 1, test.text, test.reason); err == nil {
			t.Fatalf("accepted text=%q reason=%q", test.text, test.reason)
		}
	}
	if store.WriteCount() != 0 {
		t.Fatalf("failed validation performed %d writes", store.WriteCount())
	}
}
