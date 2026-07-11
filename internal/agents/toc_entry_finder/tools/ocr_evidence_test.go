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

func TestValidateCandidatePageAcceptsUnlabeledStandaloneAllCapsHeading(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(133).SetOcrMarkdown(`112 Assistant Secretary of State 1945

This preceding discussion supplies more than enough substantive body text to
prove that the target is not a running header at the page lead. It ends here.


THE WAR ENDS AND I RESIGN

When the President and the Secretary went to Potsdam, events moved quickly.`)
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:     "The War Ends and I Resign",
			LevelName: "section",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 133)
	if err != nil {
		t.Fatal(err)
	}
	if rejection != "" {
		t.Fatalf("standalone source heading rejected: %q (%#v)", rejection, evidence)
	}
	if !evidence.TitleInSectionHeader {
		t.Fatalf("standalone source heading was not promoted to section evidence: %#v", evidence)
	}
	ready, args := tools.writeResultRecommendation(133, evidence, false)
	if !ready || args["scan_page"] != 133 {
		t.Fatalf("write recommendation = ready %v, args %#v", ready, args)
	}
}

func TestAnalyzePageEvidenceRejectsUnlabeledBodyMentionAsHeading(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:     "The War Ends and I Resign",
			LevelName: "section",
		},
	})

	evidence := tools.AnalyzePageEvidence(`A long body paragraph discusses how
the war ends and I resign, but the phrase is not isolated or capitalized as a
source heading and must remain ordinary body evidence.`, 133, false)
	if evidence.TitleInSectionHeader {
		t.Fatalf("body mention promoted to section evidence: %#v", evidence)
	}
}

func TestAnalyzePageEvidence_NumberedPartTitlePage(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "One GATHERING",
			LevelName:         "part",
			PrintedPageNumber: "37",
		},
	})

	ocr := "PART ONE\n\n# GATHERING\n\nI am sure you will catch on."
	evidence := tools.AnalyzePageEvidence(ocr, 26, false)
	if !evidence.TitleInSectionHeader {
		t.Fatalf("expected split numbered-part title evidence: %#v", evidence)
	}

	withoutLevelMarker := tools.AnalyzePageEvidence("# GATHERING\n\nAn incidental heading.", 27, false)
	if withoutLevelMarker.TitleInSectionHeader {
		t.Fatalf("generic heading matched without PART ONE marker: %#v", withoutLevelMarker)
	}

	romanTools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "I GATHERING",
			LevelName:         "part",
			PrintedPageNumber: "37",
		},
	})
	incidentalPhrase := romanTools.AnalyzePageEvidence("# GATHERING\n\nTaking part in the meeting.", 27, false)
	if incidentalPhrase.TitleInSectionHeader {
		t.Fatalf("PART I matched inside incidental 'part in' text: %#v", incidentalPhrase)
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

func TestValidateCandidatePageAcceptsUnlabeledExactTitleAtPageLead(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 300
	book.GetOrCreatePage(172).SetOcrMarkdown("The preceding chapter ends on this page.")
	book.GetOrCreatePage(173).SetOcrMarkdown(`Chapter 5

Creating the “Family Circle”
The Tortuous Path to Tehran, 1942–43

As relations with Moscow soured, Roosevelt blamed Stalin's isolation.`)

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "Creating the Family Circle The Tortuous Path to Tehran 1942 43",
			EntryNumber:       "5",
			LevelName:         "chapter",
			PrintedPageNumber: "163",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 173)
	if err != nil {
		t.Fatal(err)
	}
	if rejection != "" {
		t.Fatalf("unlabeled opener rejected: %q (%#v)", rejection, evidence)
	}
	if !evidence.TitleAtPageLead || !evidence.StartsTitleLeadCluster {
		t.Fatalf("missing page-lead evidence: %#v", evidence)
	}
}

func TestValidateCandidatePageRejectsFormalHeadingInsideDetectedContentsRange(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 446
	book.SetTocPageRange(7, 10)
	book.GetOrCreatePage(7).SetOcrMarkdown(`# CONTENTS

## BOOK I BECOMING AN AMERICAN

1. ELLIS ISLAND AND A TRAGEDY IN TEXAS`)
	book.GetOrCreatePage(13).SetOcrMarkdown(`BOOK I

## BECOMING AN AMERICAN`)

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:     "BECOMING AN AMERICAN",
			LevelName: "part",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 7)
	if err != nil {
		t.Fatal(err)
	}
	if rejection != "scan_page 7 is inside the detected contents range 7-10, not an entry opener" {
		t.Fatalf("contents candidate rejection = %q", rejection)
	}
	if evidence.TargetTitle != "" || evidence.TitleFound {
		t.Fatalf("contents range should reject before treating headings as evidence: %#v", evidence)
	}

	_, rejection, err = tools.ValidateCandidatePage(context.Background(), 13)
	if err != nil {
		t.Fatal(err)
	}
	if rejection != "" {
		t.Fatalf("source divider outside contents range rejected: %q", rejection)
	}
}

func TestValidateCandidatePageAcceptsUnlabeledTitleAtLeadWithBoundedOCRTypo(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(82).SetOcrMarkdown("The preceding chapter concludes.")
	book.GetOrCreatePage(83).SetOcrMarkdown(`Cooperating for Victory:
Defeating Germany and Javan

In August, 1943, William C. Bullitt submitted a memorandum.`)

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:             "Cooperating for Victory Defeating Germany and Japan",
			EntryNumber:       "3",
			LevelName:         "chapter",
			PrintedPageNumber: "63",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 83)
	if err != nil {
		t.Fatal(err)
	}
	if rejection != "" || !evidence.TitleAtPageLead {
		t.Fatalf("bounded lead typo was not accepted: rejection=%q evidence=%#v", rejection, evidence)
	}
}

func TestValidateCandidatePageRejectsUnlabeledContentsListing(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 300
	book.GetOrCreatePage(2).SetOcrMarkdown("Copyright page")
	book.GetOrCreatePage(3).SetOcrMarkdown(`For Benjamin and Emma

Contents
Preface: A Cemetery in Luxembourg, 5
Part I: Liberation in the West, 19`)

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:       "A Cemetery in Luxembourg",
			LevelName:   "preface",
			EntryNumber: "",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 3)
	if err != nil {
		t.Fatal(err)
	}
	if rejection == "" || !evidence.LooksLikeContentsPage {
		t.Fatalf("contents listing accepted: rejection=%q evidence=%#v", rejection, evidence)
	}
}

func TestValidateCandidatePageRejectsRepeatedUnlabeledTitleLead(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 300
	book.GetOrCreatePage(82).SetOcrMarkdown("Cooperating for Victory Defeating Germany and Japan\ncontinued body")
	book.GetOrCreatePage(83).SetOcrMarkdown("Cooperating for Victory Defeating Germany and Japan\nmore continued body")

	tools := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			Title:       "Cooperating for Victory Defeating Germany and Japan",
			EntryNumber: "3",
			LevelName:   "chapter",
		},
	})

	evidence, rejection, err := tools.ValidateCandidatePage(context.Background(), 83)
	if err != nil {
		t.Fatal(err)
	}
	if rejection == "" || evidence.StartsTitleLeadCluster {
		t.Fatalf("repeated unlabeled lead accepted: rejection=%q evidence=%#v", rejection, evidence)
	}
}
