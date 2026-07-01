package tools

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGetPageOcrTruncatesLongText(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 20
	longText := "CHAPTER FOURTEEN\n" + strings.Repeat("body text ", 4000)
	book.GetOrCreatePage(14).SetOcrMarkdown(longText)

	toolset := New(Config{
		Book:  book,
		Entry: &chapter_finder.EntryToFind{Identifier: "14", ExpectedNearPage: 14},
	})

	got, err := toolset.getPageOcr(context.Background(), 14)
	if err != nil {
		t.Fatalf("getPageOcr error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON: %v\n%s", err, got)
	}
	ocrText, _ := payload["ocr_text"].(string)
	if len([]rune(ocrText)) > maxPageOcrToolTextRunes+50 {
		t.Fatalf("ocr_text not truncated: %d runes", len([]rune(ocrText)))
	}
	if payload["ocr_text_truncated"] != true {
		t.Fatalf("ocr_text_truncated = %#v, want true", payload["ocr_text_truncated"])
	}
}
