package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGrepTextCapsMatchCount(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 400
	for page := 1; page <= 400; page++ {
		book.GetOrCreatePage(page).SetOcrMarkdown(fmt.Sprintf("page %d discussing the war effort", page))
	}

	toolset := New(Config{
		Book:  book,
		Entry: &chapter_finder.EntryToFind{Identifier: "14", ExpectedNearPage: 200},
	})

	got, err := toolset.grepText(context.Background(), "war")
	if err != nil {
		t.Fatalf("grepText error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON: %v\n%s", err, got)
	}
	matches, _ := payload["matches"].([]any)
	if len(matches) > maxGrepMatches {
		t.Fatalf("returned %d matches, want <= %d", len(matches), maxGrepMatches)
	}
	if payload["matches_truncated"] != true {
		t.Fatalf("matches_truncated = %#v, want true", payload["matches_truncated"])
	}
	if total, _ := payload["total_match_pages"].(float64); int(total) != 400 {
		t.Fatalf("total_match_pages = %#v, want 400", payload["total_match_pages"])
	}
}

// TestGrepTextCapKeepsIsolatedAndNearMatches verifies the truncation cap both
// (a) preserves isolated far-away chapter-start candidates (recall) and
// (b) biases the filler toward the entry's expected page.
func TestGrepTextCapKeepsIsolatedAndNearMatches(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 400
	// Dense contiguous cluster near the expected page, plus two isolated matches
	// far away that must not be dropped by the cap.
	set := func(p int) { book.GetOrCreatePage(p).SetOcrMarkdown("the widget appears here") }
	for p := 190; p <= 260; p++ { // 71-page cluster
		set(p)
	}
	set(5)   // isolated, far below
	set(395) // isolated, far above

	toolset := New(Config{
		Book:  book,
		Entry: &chapter_finder.EntryToFind{Identifier: "14", ExpectedNearPage: 200},
	})

	got, err := toolset.grepText(context.Background(), "widget")
	if err != nil {
		t.Fatalf("grepText error: %v", err)
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON: %v\n%s", err, got)
	}

	rawMatches, _ := payload["matches"].([]any)
	if len(rawMatches) > maxGrepMatches {
		t.Fatalf("returned %d matches, want <= %d", len(rawMatches), maxGrepMatches)
	}
	if payload["matches_truncated"] != true {
		t.Fatalf("matches_truncated = %#v, want true", payload["matches_truncated"])
	}
	pages := map[int]bool{}
	for _, m := range rawMatches {
		mm, _ := m.(map[string]any)
		if sp, ok := mm["scan_page"].(float64); ok {
			pages[int(sp)] = true
		}
	}
	// Recall: isolated candidates and the cluster start survive.
	for _, p := range []int{5, 190, 395} {
		if !pages[p] {
			t.Fatalf("expected isolated/cluster-start page %d to survive truncation; kept=%v", p, pages)
		}
	}
	// Nearness bias: the expected page is kept, a far cluster tail page is dropped.
	if !pages[200] {
		t.Fatalf("expected near page 200 to survive; kept=%v", pages)
	}
	if pages[260] {
		t.Fatalf("far page 260 (distance 60) should have been dropped by the near-bias fill; kept=%v", pages)
	}
}
