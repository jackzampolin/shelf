package tools

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func newWriteResultTestTools() *TocEntryFinderTools {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(93).SetOcrMarkdown(`<div data-label="Page-Header">Platform for Invasion</div>
<div data-label="Text"><p>Discussion of cross-Channel planning continued.</p></div>`)
	book.GetOrCreatePage(99).SetOcrMarkdown(`<div data-label="Page-Header">Platform for Invasion</div>
<div data-label="Text"><p>The earlier operation remained under discussion.</p></div>`)
	book.GetOrCreatePage(100).SetOcrMarkdown(`<div data-label="Page-Header">Planning 'Torch'</div>
<div data-label="Text"><p>At Allied headquarters the next operation took shape.</p></div>`)

	return New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "5",
			LevelName:         "chapter",
			Title:             `PLANNING "TORCH"`,
			PrintedPageNumber: "83",
		},
	})
}

func TestWriteResultRejectsPageWithoutTargetEvidence(t *testing.T) {
	toolset := newWriteResultTestTools()

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(93),
		"reasoning": "guessed from expected range",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if toolset.IsComplete() {
		t.Fatal("writeResult completed despite missing OCR evidence")
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	if payload["success"] != false {
		t.Fatalf("success = %#v, want false; payload=%#v", payload["success"], payload)
	}
	if payload["error"] != "write_result rejected" {
		t.Fatalf("unexpected error payload: %#v", payload)
	}
}

func newInvasionWriteResultTestTools() *TocEntryFinderTools {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(124).SetOcrMarkdown(`<div data-label="Page-Header">Platform for Invasion</div>
<div data-label="Text"><p>The preceding chapter closed.</p></div>`)
	book.GetOrCreatePage(125).SetOcrMarkdown(`<div data-label="Section-Header">CHAPTER SIX</div>
<div data-label="Section-Header">Invasion of Africa</div>
<div data-label="Text"><p>The invasion opened in North Africa.</p></div>`)
	book.GetOrCreatePage(126).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Text"><p>The first convoys continued inland.</p></div>`)
	book.GetOrCreatePage(129).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Text"><p>The campaign was now well underway.</p></div>`)
	book.GetOrCreatePage(130).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Text"><p>Another paragraph continued the same chapter.</p></div>`)
	book.GetOrCreatePage(131).SetOcrMarkdown(`<div data-label="Text"><p>Later historians often referred to chapter six when discussing the operation.</p></div>`)

	return New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "6",
			LevelName:         "chapter",
			Title:             "Invasion of Africa",
			PrintedPageNumber: "114",
		},
	})
}

func TestWriteResultAcceptsFormalSectionHeader(t *testing.T) {
	toolset := newInvasionWriteResultTestTools()

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(125),
		"reasoning": "OCR section headers match chapter number and title",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if !toolset.IsComplete() {
		t.Fatalf("writeResult rejected formal section header: %s", got)
	}
}

func TestWriteResultAcceptsMissingExpectedPrintedPageBoundary(t *testing.T) {
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
			EntryNumber:       "7",
			LevelName:         "chapter",
			Title:             "WINTER IN ALGIERS",
			PrintedPageNumber: "128",
		},
	})

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(147),
		"reasoning": "first available scan page after printed page 128 is missing",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if !toolset.IsComplete() {
		t.Fatalf("writeResult rejected missing-page boundary: %s", got)
	}
}

func TestWriteResultAcceptsAppendixTitlePrefixSectionHeader(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	book.GetOrCreatePage(586).SetOcrMarkdown(`<div data-label="Page-Header">552</div>
<div data-label="Section-Header"><h2>B. THE ALLIED AIR-GROUND TEAM</h2></div>
<div data-label="Diagram"><pre>SUPREME HEADQUARTERS ALLIED</pre></div>`)
	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "B",
			LevelName:         "appendix",
			Title:             "The Allied Air-ground Team for the Final Offensive",
			PrintedPageNumber: "552",
		},
		TargetIsBackMatter: true,
		BackMatterStart:    557,
	})

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(586),
		"reasoning": "appendix B section header contains distinctive title prefix",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if !toolset.IsComplete() {
		t.Fatalf("writeResult rejected appendix title prefix: %s", got)
	}
}

func TestWriteResultRejectsRepeatedRunningHeader(t *testing.T) {
	toolset := newInvasionWriteResultTestTools()

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(130),
		"reasoning": "OCR page header matches title",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if toolset.IsComplete() {
		t.Fatal("writeResult completed for a repeated running header")
	}
	if !strings.Contains(got, "repeated running header") {
		t.Fatalf("expected repeated running header rejection, got: %s", got)
	}
}

func TestWriteResultRejectsEntryNumberOutsideSectionHeader(t *testing.T) {
	toolset := newInvasionWriteResultTestTools()

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(131),
		"reasoning": "OCR mentions chapter six",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if toolset.IsComplete() {
		t.Fatal("writeResult completed for an incidental entry-number mention")
	}
	if !strings.Contains(got, "entry number appears only outside a formal section header") {
		t.Fatalf("expected entry-number rejection, got: %s", got)
	}
}

func TestWriteResultAcceptsPageWithTargetEvidence(t *testing.T) {
	toolset := newWriteResultTestTools()

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(100),
		"reasoning": "OCR page header matches title",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if !toolset.IsComplete() {
		t.Fatalf("writeResult did not complete for matching OCR page: %s", got)
	}

	result, ok := toolset.GetResult().(*toc_entry_finder.Result)
	if !ok || result == nil || result.ScanPage == nil || *result.ScanPage != 100 {
		t.Fatalf("unexpected tool result: %#v", toolset.GetResult())
	}
}

func TestWriteResultAcceptsStoredHeaderWithCleanMarkdown(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(99).SetOcrMarkdown("The preceding operation remained under discussion.")
	book.GetOrCreatePage(99).SetHeader("Platform for Invasion\n82")
	book.GetOrCreatePage(100).SetOcrMarkdown("At Allied headquarters the next operation took shape.")
	book.GetOrCreatePage(100).SetHeader("Planning \"Torch\"\n83")

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "5",
			LevelName:         "chapter",
			Title:             `PLANNING "TORCH"`,
			PrintedPageNumber: "83",
		},
	})

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"scan_page": float64(100),
		"reasoning": "stored Chandra page header matches title",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if !toolset.IsComplete() {
		t.Fatalf("writeResult rejected clean OCR with stored header evidence: %s", got)
	}
}

func TestWriteResultRejectsMissingScanPage(t *testing.T) {
	toolset := newWriteResultTestTools()

	got, err := toolset.writeResult(context.Background(), map[string]any{
		"reasoning": "not found",
	})
	if err != nil {
		t.Fatalf("writeResult error: %v", err)
	}
	if toolset.IsComplete() {
		t.Fatal("writeResult completed despite missing scan_page")
	}
	if got == "" {
		t.Fatal("expected rejection payload")
	}
}
