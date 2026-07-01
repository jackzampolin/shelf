package tools

import (
	"context"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestAnalyzePageEvidence_TitleHeaderInExpectedWindow(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             `PLANNING "OVERLORD"`,
			EntryNumber:       "13",
			LevelName:         "chapter",
			PrintedPageNumber: "242",
		},
	})

	ocr := `<div data-label="Page-Header">Planning "Overlord"</div>
<div data-label="Page-Header">245</div>
<div data-label="Text"><p>studied in detail only by professionals and by technical schools.</p></div>`

	evidence := tools.AnalyzePageEvidence(ocr, 258, false)
	if !evidence.TitleFound || !evidence.TitleInPageHeader {
		t.Fatalf("expected title evidence in page header: %#v", evidence)
	}
	if !evidence.InExpectedScanWindow {
		t.Fatalf("expected page to be in scan window: %#v", evidence.ExpectedScanWindow)
	}
	if evidence.DecisionGuidance == "" {
		t.Fatal("expected decision guidance")
	}
}

func TestAnalyzePageEvidence_FormalSectionHeader(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "Invasion of Africa",
			EntryNumber:       "6",
			LevelName:         "chapter",
			PrintedPageNumber: "114",
		},
	})

	ocr := `<div data-label="Section-Header">CHAPTER SIX</div>
<div data-label="Section-Header">Invasion of Africa</div>
<div data-label="Text"><p>The invasion opened in North Africa.</p></div>`

	evidence := tools.AnalyzePageEvidence(ocr, 125, false)
	if !evidence.TitleInSectionHeader {
		t.Fatalf("expected title in section header: %#v", evidence)
	}
	if !evidence.EntryNumberInSectionHeader {
		t.Fatalf("expected entry number in section header: %#v", evidence)
	}
	if len(evidence.SectionHeaderText) != 2 {
		t.Fatalf("section headers = %#v, want two headers", evidence.SectionHeaderText)
	}
}

func TestAnalyzePageEvidence_AppendixTitlePrefixSectionHeader(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "The Allied Air-ground Team for the Final Offensive",
			EntryNumber:       "B",
			LevelName:         "appendix",
			PrintedPageNumber: "552",
		},
	})

	ocr := `<div data-label="Page-Header">552</div>
<div data-label="Section-Header"><h2>B. THE ALLIED AIR-GROUND TEAM</h2></div>
<div data-label="Diagram"><pre>SUPREME HEADQUARTERS ALLIED</pre></div>`

	evidence := tools.AnalyzePageEvidence(ocr, 586, false)
	if !evidence.TitlePrefixInSectionHeader {
		t.Fatalf("expected title prefix in section header: %#v", evidence)
	}
	if !evidence.EntryNumberInSectionHeader {
		t.Fatalf("expected appendix letter in section header: %#v", evidence)
	}
	if !evidence.TitleFound {
		t.Fatalf("expected title found via prefix: %#v", evidence)
	}
}

func TestEntryNumberFoundRecognizesSpelledChapter(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "WINTER IN ALGIERS",
			EntryNumber:       "7",
			LevelName:         "chapter",
			PrintedPageNumber: "128",
		},
	})

	if !tools.entryNumberFound("CHAPTER SEVEN Winter in Algiers") {
		t.Fatal("expected spelled chapter number to match")
	}
}

func TestValidateCandidatePageMarksMissingExpectedPrintedPage(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(146).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Page-Header">127</div>
<div data-label="Text"><p>In the eastern sector, Tunisia, it was different.</p></div>`)
	book.GetOrCreatePage(147).SetOcrMarkdown(`<div data-label="Page-Header">Winter in Algiers</div>
<div data-label="Page-Header">129</div>
<div data-label="Text"><p>The air power of the Axis in Sicily remained strong.</p></div>`)

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "WINTER IN ALGIERS",
			EntryNumber:       "7",
			LevelName:         "chapter",
			PrintedPageNumber: "128",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 147)
	if err != nil {
		t.Fatalf("ValidateCandidatePage error: %v", err)
	}
	if rejection != "" {
		t.Fatalf("expected missing printed page boundary to be accepted, got rejection %q with evidence %#v", rejection, evidence)
	}
	if !evidence.StartsTitleHeaderCluster {
		t.Fatalf("expected start of title header cluster: %#v", evidence)
	}
	if !evidence.ExpectedPrintedPageMissing {
		t.Fatalf("expected missing printed page evidence: %#v", evidence)
	}
	if evidence.PreviousPrintedPageNumber != 127 || evidence.PrintedPageNumber != 129 {
		t.Fatalf("printed page boundary = %d -> %d, want 127 -> 129", evidence.PreviousPrintedPageNumber, evidence.PrintedPageNumber)
	}
}

func TestValidateCandidatePageAcceptsNearTitleHeaderMatch(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(146).SetOcrMarkdown(`<div data-label="Page-Header">Invasion of Africa</div>
<div data-label="Page-Header">127</div>
<div data-label="Text"><p>In the eastern sector, Tunisia, it was different.</p></div>`)
	book.GetOrCreatePage(147).SetOcrMarkdown(`<div data-label="Page-Header">Winter in Algiers</div>
<div data-label="Page-Header">129</div>
<div data-label="Text"><p>The air power of the Axis in Sicily remained strong.</p></div>`)

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "WINTER IN ALGERS",
			EntryNumber:       "7",
			LevelName:         "chapter",
			PrintedPageNumber: "128",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 147)
	if err != nil {
		t.Fatalf("ValidateCandidatePage error: %v", err)
	}
	if rejection != "" {
		t.Fatalf("expected near title match to be accepted, got rejection %q with evidence %#v", rejection, evidence)
	}
	if !evidence.TitleInPageHeader || !evidence.StartsTitleHeaderCluster {
		t.Fatalf("expected near title page-header evidence: %#v", evidence)
	}
}
