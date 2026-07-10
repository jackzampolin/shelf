package common

import (
	"context"
	"testing"
)

func TestRepairOCRPagesSelectivelyDeletesResultsAndResetsPages(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	store.SetDoc("Page", "page-1", map[string]any{
		"_bookID":      "book-1",
		"page_num":     1,
		"ocr_complete": true,
		"ocr_markdown": "keep page one",
	})
	store.SetDoc("Page", "page-2", map[string]any{
		"_bookID":      "book-1",
		"page_num":     2,
		"ocr_complete": true,
		"ocr_markdown": "bad page two",
		"headings":     "[]",
		"header":       "header",
		"footer":       "footer",
	})
	store.SetDoc("OcrResult", "ocr-page-1-primary", map[string]any{
		"_pageID": "page-1", "provider": "primary", "text": "keep",
	})
	store.SetDoc("OcrResult", "ocr-page-2-primary-a", map[string]any{
		"_pageID": "page-2", "provider": "primary", "text": "",
	})
	store.SetDoc("OcrResult", "ocr-page-2-primary-b", map[string]any{
		"_pageID": "page-2", "provider": "primary", "text": "duplicate",
	})
	store.SetDoc("OcrResult", "ocr-page-2-secondary", map[string]any{
		"_pageID": "page-2", "provider": "secondary", "text": "preserve",
	})

	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 2
	book.OcrProviders = []string{"primary", "secondary"}
	page1 := book.GetOrCreatePage(1)
	page1.SetPageDocID("page-1")
	page1.MarkOcrComplete("primary", "keep")
	page1.MarkOcrComplete("secondary", "keep secondary")
	page2 := book.GetOrCreatePage(2)
	page2.SetPageDocID("page-2")
	page2.MarkOcrComplete("primary", "")
	page2.MarkOcrComplete("secondary", "preserve")
	page2.SetOcrMarkdownWithHeadings("bad page two", []HeadingItem{{Text: "Bad"}})
	page2.SetHeader("header")
	page2.SetFooter("footer")

	result, err := RepairOCRPages(context.Background(), book, []int{2, 2}, []string{"primary"})
	if err != nil {
		t.Fatalf("RepairOCRPages: %v", err)
	}
	if len(result.Pages) != 1 || result.Pages[0] != 2 {
		t.Fatalf("repaired pages = %v, want [2]", result.Pages)
	}
	if result.DeletedResults != 2 {
		t.Fatalf("deleted results = %d, want both duplicate primary rows", result.DeletedResults)
	}
	if store.GetDoc("OcrResult", "ocr-page-2-primary-a") != nil || store.GetDoc("OcrResult", "ocr-page-2-primary-b") != nil {
		t.Fatal("target provider OCR rows were not deleted")
	}
	if store.GetDoc("OcrResult", "ocr-page-2-secondary") == nil || store.GetDoc("OcrResult", "ocr-page-1-primary") == nil {
		t.Fatal("unrelated OCR rows were deleted")
	}

	pageDoc := store.GetDoc("Page", "page-2")
	if pageDoc["ocr_complete"] != false {
		t.Fatalf("page ocr_complete = %v, want false", pageDoc["ocr_complete"])
	}
	for _, field := range []string{"ocr_markdown", "headings", "header", "footer"} {
		if _, ok := pageDoc[field]; ok {
			t.Fatalf("page field %s survived repair: %#v", field, pageDoc[field])
		}
	}
	if page2.OcrComplete("primary") {
		t.Fatal("target provider remained complete in memory")
	}
	if !page2.OcrComplete("secondary") {
		t.Fatal("non-target provider was cleared in memory")
	}
	if page2.GetOcrMarkdown() != "" || page2.GetHeader() != "" || page2.GetFooter() != "" || page2.GetHeadings() != nil {
		t.Fatal("derived in-memory OCR fields were not cleared")
	}
	if !page1.OcrComplete("primary") || store.GetDoc("Page", "page-1")["ocr_markdown"] != "keep page one" {
		t.Fatal("unselected page was modified")
	}
}

func TestRepairOCRPagesIsIdempotent(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Page", "page-1", map[string]any{"page_num": 1, "ocr_complete": true})
	store.SetDoc("OcrResult", "ocr-1", map[string]any{
		"_pageID": "page-1", "provider": "primary", "text": "",
	})
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	book.OcrProviders = []string{"primary"}
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")
	page.MarkOcrComplete("primary", "")

	first, err := RepairOCRPages(context.Background(), book, []int{1}, []string{"primary"})
	if err != nil {
		t.Fatal(err)
	}
	second, err := RepairOCRPages(context.Background(), book, []int{1}, []string{"primary"})
	if err != nil {
		t.Fatal(err)
	}
	if first.DeletedResults != 1 || second.DeletedResults != 0 {
		t.Fatalf("deleted counts = %d then %d, want 1 then 0", first.DeletedResults, second.DeletedResults)
	}
	if page.OcrComplete("primary") {
		t.Fatal("page became complete after idempotent repair")
	}
}

func TestRepairOCRPagesValidatesBeforeWriting(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Page", "page-1", map[string]any{"page_num": 1, "ocr_complete": true})
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	book.OcrProviders = []string{"primary"}
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")
	page.MarkOcrComplete("primary", "text")

	if _, err := RepairOCRPages(context.Background(), book, []int{2}, []string{"primary"}); err == nil {
		t.Fatal("out-of-range page error = nil")
	}
	if _, err := RepairOCRPages(context.Background(), book, []int{1}, []string{"typo"}); err == nil {
		t.Fatal("unconfigured provider error = nil")
	}
	if store.GetDoc("Page", "page-1")["ocr_complete"] != true || !page.OcrComplete("primary") {
		t.Fatal("validation failure modified page state")
	}
}
