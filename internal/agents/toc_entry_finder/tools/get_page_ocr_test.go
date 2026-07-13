package tools

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGetPageOcrReturnsCompactTextWithEvidence(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 20
	longText := `<div data-label="Section-Header">CHAPTER ONE</div>
<div data-label="Section-Header">Prelude to War</div>
<div data-label="Text"><p>` + strings.Repeat("body text ", 400) + `</p></div>`
	book.GetOrCreatePage(17).SetOcrMarkdown(longText)

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "Prelude to War",
			EntryNumber:       "1",
			LevelName:         "chapter",
			PrintedPageNumber: "3",
		},
	})

	got, err := toolset.getPageOcr(context.Background(), 17)
	if err != nil {
		t.Fatalf("getPageOcr error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	ocrText, _ := payload["ocr_text"].(string)
	if len([]rune(ocrText)) > maxPageOcrToolTextRunes+120 {
		t.Fatalf("ocr_text was not compacted: %d runes", len([]rune(ocrText)))
	}
	if payload["ocr_text_truncated"] != true {
		t.Fatalf("ocr_text_truncated = %#v, want true", payload["ocr_text_truncated"])
	}
	if omitted, _ := payload["omitted_char_count"].(float64); omitted <= 0 {
		t.Fatalf("omitted_char_count = %#v, want > 0", payload["omitted_char_count"])
	}
	if !strings.Contains(ocrText, "CHAPTER ONE") || !strings.Contains(ocrText, "Prelude to War") {
		t.Fatalf("compact OCR text lost opener evidence: %s", ocrText)
	}

	evidence, ok := payload["evidence"].(map[string]any)
	if !ok {
		t.Fatalf("missing evidence object: %#v", payload["evidence"])
	}
	if evidence["title_in_section_header"] != true {
		t.Fatalf("title_in_section_header = %#v, want true", evidence["title_in_section_header"])
	}
	if evidence["entry_number_in_section_header"] != true {
		t.Fatalf("entry_number_in_section_header = %#v, want true", evidence["entry_number_in_section_header"])
	}
}

func TestGetPageOcrReportsMissingPrintedPageBoundary(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(146).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Page-Header">127</div>
<div data-label="Text"><p>In the eastern sector, Tunisia, it was different.</p></div>`)
	book.GetOrCreatePage(147).SetOcrMarkdown(`<div data-label="Page-Header">Winter in Algiers</div>
<div data-label="Page-Header">129</div>
<div data-label="Text"><p>The air power of the Axis in Sicily remained strong.</p></div>`)

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "WINTER IN ALGIERS",
			EntryNumber:       "7",
			LevelName:         "chapter",
			PrintedPageNumber: "128",
		},
	})

	got, err := toolset.getPageOcr(context.Background(), 147)
	if err != nil {
		t.Fatalf("getPageOcr error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	evidence, ok := payload["evidence"].(map[string]any)
	if !ok {
		t.Fatalf("missing evidence object: %#v", payload["evidence"])
	}
	if evidence["starts_title_header_cluster"] != true {
		t.Fatalf("starts_title_header_cluster = %#v, want true; evidence=%#v", evidence["starts_title_header_cluster"], evidence)
	}
	if evidence["expected_printed_page_missing"] != true {
		t.Fatalf("expected_printed_page_missing = %#v, want true; evidence=%#v", evidence["expected_printed_page_missing"], evidence)
	}
	guidance, _ := evidence["decision_guidance"].(string)
	if !strings.Contains(guidance, "absent from the scan set") {
		t.Fatalf("guidance did not explain missing printed page: %q", guidance)
	}
}

func TestGetPageOcrRecommendsWriteResultForAppendixPrefix(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	book.GetOrCreatePage(586).SetOcrMarkdown(`## B. THE ALLIED AIR-GROUND TEAM

Organizational chart of the Allied Air-Ground Team.`)

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "The Allied Air-ground Team for the Final Offensive",
			EntryNumber:       "B",
			LevelName:         "appendix",
			PrintedPageNumber: "552",
		},
		TargetIsBackMatter: true,
	})

	got, err := toolset.getPageOcr(context.Background(), 586)
	if err != nil {
		t.Fatalf("getPageOcr error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	if payload["write_result_ready"] != true {
		t.Fatalf("write_result_ready = %#v, want true; payload=%#v", payload["write_result_ready"], payload)
	}
	args, ok := payload["write_result_args"].(map[string]any)
	if !ok {
		t.Fatalf("missing write_result_args: %#v", payload["write_result_args"])
	}
	if scanPage, _ := args["scan_page"].(float64); int(scanPage) != 586 {
		t.Fatalf("scan_page = %#v, want 586", args["scan_page"])
	}
}

func TestGetPageOcrDoesNotRecommendBackMatterForBodyEntry(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	book.GetOrCreatePage(580).SetOcrMarkdown(`<div data-label="Section-Header">Breakout</div>
<div data-label="Text"><p>Footnote reference text.</p></div>`)

	toolset := New(Config{
		Book:            book,
		BackMatterStart: 550,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "BREAKOUT",
			EntryNumber:       "15",
			LevelName:         "chapter",
			PrintedPageNumber: "292",
		},
	})

	got, err := toolset.getPageOcr(context.Background(), 580)
	if err != nil {
		t.Fatalf("getPageOcr error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	if payload["write_result_ready"] != false {
		t.Fatalf("write_result_ready = %#v, want false; payload=%#v", payload["write_result_ready"], payload)
	}
}
