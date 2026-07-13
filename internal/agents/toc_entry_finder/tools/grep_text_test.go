package tools

import (
	"context"
	"encoding/json"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGrepTextCapsContextSnippets(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 40
	for page := 10; page <= 34; page++ {
		book.GetOrCreatePage(page).SetOcrMarkdown(`<div data-label="Page-Header">Planning Overlord</div>
<div data-label="Text"><p>Planning Overlord appears in this running header cluster with enough surrounding prose to make snippets expensive.</p></div>`)
	}

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "13",
			LevelName:         "chapter",
			Title:             "PLANNING OVERLORD",
			PrintedPageNumber: "1",
		},
	})

	got, err := toolset.grepText(context.Background(), "Planning Overlord")
	if err != nil {
		t.Fatalf("grepText error: %v", err)
	}

	var payload struct {
		Matches               []GrepMatch `json:"matches"`
		Clusters              []Cluster   `json:"clusters"`
		SnippetsIncludedPages int         `json:"snippets_included_pages"`
		SnippetsOmittedPages  int         `json:"snippets_omitted_pages"`
	}
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	if len(payload.Matches) != 25 {
		t.Fatalf("matches = %d, want 25", len(payload.Matches))
	}
	if len(payload.Clusters) != 1 || payload.Clusters[0].StartPage != 10 || payload.Clusters[0].EndPage != 34 {
		t.Fatalf("unexpected clusters: %#v", payload.Clusters)
	}
	if payload.SnippetsIncludedPages > maxGrepSnippetPages {
		t.Fatalf("included snippets = %d, want <= %d", payload.SnippetsIncludedPages, maxGrepSnippetPages)
	}
	if payload.SnippetsOmittedPages == 0 {
		t.Fatalf("expected some snippets to be omitted: %#v", payload)
	}
}

func TestGrepTextSurfacesApproximateTargetTitleMatches(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 200
	book.GetOrCreatePage(147).SetOcrMarkdown(`<div data-label="Page-Header">Winter in Algiers</div>
<div data-label="Page-Header">129</div>
<div data-label="Text"><p>The air power of the Axis in Sicily remained strong.</p></div>`)

	toolset := New(Config{
		Book: book,
		Entry: &toc_entry_finder.TocEntry{
			EntryNumber:       "7",
			LevelName:         "chapter",
			Title:             "WINTER IN ALGERS",
			PrintedPageNumber: "128",
		},
	})

	got, err := toolset.grepText(context.Background(), "WINTER IN ALGERS")
	if err != nil {
		t.Fatalf("grepText error: %v", err)
	}

	var payload struct {
		Matches               []GrepMatch `json:"matches"`
		ApproximateTitleMatch bool        `json:"approximate_title_match"`
	}
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON result: %v\n%s", err, got)
	}
	if !payload.ApproximateTitleMatch {
		t.Fatalf("expected approximate title match payload: %s", got)
	}
	if len(payload.Matches) != 1 || payload.Matches[0].ScanPage != 147 {
		t.Fatalf("matches = %#v, want page 147", payload.Matches)
	}
}
