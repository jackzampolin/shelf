package common

import (
	"context"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRepairPDFTextPagesPersistsRealTextAndClearsQuarantine(t *testing.T) {
	binDir := t.TempDir()
	script := filepath.Join(binDir, "pdftotext")
	text := "# Chapter 3\n\n" + strings.Repeat("Real embedded PDF text. ", 8)
	expectedText := strings.TrimSpace(text)
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf '%s\\f' '"+text+"'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH"))

	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	book.OcrProviders = []string{"chandra-local"}
	book.PDFs = PDFList{{Path: filepath.Join(t.TempDir(), "book.pdf"), StartPage: 1, EndPage: 1}}
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")
	page.QuarantineOCR("old model failure")
	store.SetDoc("Page", "page-1", map[string]any{
		"ocr_complete":          false,
		"ocr_quarantined":       true,
		"ocr_quarantine_reason": "old model failure",
	})
	store.SetDoc("OcrResult", "old-result", map[string]any{
		"_pageID":  "page-1",
		"provider": "chandra-local",
		"text":     "partial",
	})

	result, err := RepairPDFTextPages(context.Background(), book, []int{1}, 50)
	if err != nil {
		t.Fatal(err)
	}
	if result.DeletedResults != 1 || result.Characters != len(expectedText) {
		t.Fatalf("result = %#v", result)
	}
	doc := store.GetDoc("Page", "page-1")
	if doc["ocr_complete"] != true || doc["ocr_quarantined"] != false || doc["ocr_markdown"] != expectedText {
		t.Fatalf("page doc = %#v", doc)
	}
	if _, ok := doc["ocr_quarantine_reason"]; ok {
		t.Fatalf("quarantine reason was not cleared: %#v", doc)
	}
	if store.GetDoc("OcrResult", "old-result") != nil {
		t.Fatal("old OCR result was not deleted")
	}
	pdfResult := store.GetDoc("OcrResult", "auto-OcrResult-1")
	if pdfResult["provider"] != PDFTextProvider || pdfResult["text"] != expectedText {
		t.Fatalf("PDF text result = %#v", pdfResult)
	}
	if !page.IsOCRComplete() || !page.OcrResolved(book.OcrProviders) {
		t.Fatal("text-native repair did not resolve in-memory page state")
	}
	if page.OcrComplete("chandra-local") {
		t.Fatal("text-native repair masqueraded as Chandra output")
	}
	if quarantined, _ := page.OCRQuarantine(); quarantined {
		t.Fatal("text-native repair left page quarantined")
	}
}

func TestRepairPDFTextPagesRejectsMissingTextBeforeWrites(t *testing.T) {
	binDir := t.TempDir()
	script := filepath.Join(binDir, "pdftotext")
	if err := os.WriteFile(script, []byte("#!/bin/sh\nprintf 'tiny\\f'\n"), 0o755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PATH", binDir+string(os.PathListSeparator)+os.Getenv("PATH"))
	store := NewMemoryStateStore()
	book := NewBookState("book-1")
	book.Store = store
	book.TotalPages = 1
	book.PDFs = PDFList{{Path: "book.pdf", StartPage: 1, EndPage: 1}}
	page := book.GetOrCreatePage(1)
	page.SetPageDocID("page-1")
	store.SetDoc("Page", "page-1", map[string]any{"ocr_complete": false})

	if _, err := RepairPDFTextPages(context.Background(), book, []int{1}, 50); err == nil {
		t.Fatal("tiny embedded text was accepted")
	}
	if store.WriteCount() != 0 {
		t.Fatalf("failed preflight performed %d writes", store.WriteCount())
	}
}
