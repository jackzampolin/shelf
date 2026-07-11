package tools

import (
	"encoding/json"
	"strings"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGetHeadingPagesRanksTargetPrefixMatchFirst(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	book.GetOrCreatePage(582).SetOcrMarkdownWithHeadings("# Appendices\n\n## A. ALLIED ORDER OF BATTLE, FOR FINAL OFFENSIVE", []common.HeadingItem{
		{Level: 1, Text: "Appendices", LineNumber: 1},
		{Level: 2, Text: "A. ALLIED ORDER OF BATTLE, FOR FINAL OFFENSIVE", LineNumber: 3},
	})
	book.GetOrCreatePage(586).SetOcrMarkdownWithHeadings("## B. THE ALLIED AIR-GROUND TEAM", []common.HeadingItem{
		{Level: 2, Text: "B. THE ALLIED AIR-GROUND TEAM", LineNumber: 1},
	})

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "B",
			LevelName:         "appendix",
			Title:             "The Allied Air-ground Team for the Final Offensive",
			PrintedPageNumber: "552",
		},
		TargetIsBackMatter: true,
	})

	start, end := 562, 587
	got, err := toolset.getHeadingPages(&start, &end)
	if err != nil {
		t.Fatalf("getHeadingPages error: %v", err)
	}

	results := parseHeadingPageResults(t, got)
	if len(results) < 2 {
		t.Fatalf("results = %#v, want at least two headings", results)
	}
	if results[0].ScanPage != 586 {
		t.Fatalf("first result page = %d, want 586; output:\n%s", results[0].ScanPage, got)
	}
	if !results[0].TargetTitlePrefixMatch || !results[0].EntryNumberMatch || !results[0].InExpectedScanWindow {
		t.Fatalf("first result missing target signals: %#v", results[0])
	}
}

func TestGetHeadingPagesChoosesTitleHeadingOverChapterNumberHeading(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 615
	book.GetOrCreatePage(471).SetOcrMarkdownWithHeadings("## CHAPTER TWENTY-ONE\n\n# Overrunning Germany", []common.HeadingItem{
		{Level: 2, Text: "CHAPTER TWENTY-ONE", LineNumber: 1},
		{Level: 1, Text: "Overrunning Germany", LineNumber: 3},
	})

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "21",
			LevelName:         "chapter",
			Title:             "OVERRUNNING GERMANY",
			PrintedPageNumber: "441",
		},
	})

	start, end := 451, 476
	got, err := toolset.getHeadingPages(&start, &end)
	if err != nil {
		t.Fatalf("getHeadingPages error: %v", err)
	}

	results := parseHeadingPageResults(t, got)
	if len(results) != 1 {
		t.Fatalf("results = %#v, want one heading", results)
	}
	if results[0].Heading.Text != "Overrunning Germany" {
		t.Fatalf("heading = %q, want title heading; output:\n%s", results[0].Heading.Text, got)
	}
	if !results[0].TargetTitleMatch || !results[0].EntryNumberMatch {
		t.Fatalf("result missing target signals: %#v", results[0])
	}
}

func TestGetHeadingPagesCapsLargeRangesAfterRanking(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 100
	for page := 1; page <= 30; page++ {
		title := "Ordinary heading"
		if page == 30 {
			title = "Tokyo"
		}
		book.GetOrCreatePage(page).SetOcrMarkdownWithHeadings("# "+title, []common.HeadingItem{
			{Level: 1, Text: title, LineNumber: 1},
		})
	}
	toolset := New(Config{
		Book:  book,
		Entry: &toc_entry_finder.TocEntry{LevelName: "section", Title: "Tokyo"},
	})
	start, end := 1, 100
	got, err := toolset.getHeadingPages(&start, &end)
	if err != nil {
		t.Fatal(err)
	}
	results := parseHeadingPageResults(t, got)
	if len(results) != maxHeadingPageResults {
		t.Fatalf("results = %d, want cap %d", len(results), maxHeadingPageResults)
	}
	if results[0].ScanPage != 30 || !results[0].TargetTitleMatch {
		t.Fatalf("target was not retained first after cap: %#v", results[0])
	}
	if !strings.Contains(got, "Found 30 pages") || !strings.Contains(got, "top 20") {
		t.Fatalf("output omitted cap accounting: %s", got)
	}
}

func parseHeadingPageResults(t *testing.T, output string) []HeadingPageResult {
	t.Helper()
	jsonStart := strings.Index(output, "[")
	if jsonStart < 0 {
		t.Fatalf("heading output did not contain JSON array:\n%s", output)
	}
	var results []HeadingPageResult
	if err := json.Unmarshal([]byte(output[jsonStart:]), &results); err != nil {
		t.Fatalf("invalid heading JSON: %v\n%s", err, output)
	}
	return results
}
