package common

import (
	"reflect"
	"testing"

	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
)

func tocString(value string) *string { return &value }

func TestNormalizeTocExtractEntriesRepairsCollapsedPreponderanceRows(t *testing.T) {
	section := "section"
	chapter := "chapter"
	entries := []extract_toc.Entry{
		{Title: "Introduction: I", Level: 1, LevelName: &chapter},
		{Title: "Fears and Threats, 3. Economics, Power, and National Security, 10. The Strategy of Preponderance, 15. Lessons of the Past, 19.", Level: 2, LevelName: &section},
		{Title: "Ambivalence, Disorganization, and the East European Litmus Test, 1945: 25", Level: 1, LevelName: &chapter},
		{Title: "War Plans, Bases, and the Budget, 221. European Priorities and Titoist Opportunities, 229. The Middle East, 237. China and Korea, 246. Japan and Southeast Asia, 253. The Dilemma of Means and Ends, 260.", Level: 2, LevelName: &section},
	}

	got, collapsed, err := normalizeTocExtractEntries(entries)
	if err != nil {
		t.Fatalf("normalizeTocExtractEntries: %v", err)
	}
	if collapsed != 2 {
		t.Fatalf("collapsed rows = %d, want 2", collapsed)
	}
	if len(got) != 12 {
		t.Fatalf("entries = %d, want 12: %#v", len(got), got)
	}

	wantTitles := []string{
		"Introduction",
		"Fears and Threats",
		"Economics, Power, and National Security",
		"The Strategy of Preponderance",
		"Lessons of the Past",
		"Ambivalence, Disorganization, and the East European Litmus Test, 1945",
		"War Plans, Bases, and the Budget",
		"European Priorities and Titoist Opportunities",
		"The Middle East",
		"China and Korea",
		"Japan and Southeast Asia",
		"The Dilemma of Means and Ends",
	}
	wantPages := []string{"I", "3", "10", "15", "19", "25", "221", "229", "237", "246", "253", "260"}
	for i := range got {
		if got[i].Title != wantTitles[i] {
			t.Errorf("entry %d title = %q, want %q", i, got[i].Title, wantTitles[i])
		}
		if got[i].PrintedPageNumber == nil || *got[i].PrintedPageNumber != wantPages[i] {
			t.Errorf("entry %d page = %v, want %q", i, got[i].PrintedPageNumber, wantPages[i])
		}
	}
}

func TestNormalizeTocExtractEntriesLeavesOrdinaryTitlesUntouched(t *testing.T) {
	page := "12"
	entries := []extract_toc.Entry{
		{Title: "Monday, June 26", Level: 2},
		{Title: "The United States, 1945-1953", Level: 1},
		{Title: "A Real Subtitle: 1945", Level: 1},
		{Title: "One, 3. Two, 2. Three, 4.", Level: 2},
		{Title: "Already Structured", Level: 1, PrintedPageNumber: &page},
	}

	got, collapsed, err := normalizeTocExtractEntries(entries)
	if err == nil {
		t.Fatal("expected non-increasing collapsed row to be rejected")
	}
	if got != nil || collapsed != 0 {
		t.Fatalf("rejected result = %#v, collapsed = %d", got, collapsed)
	}

	entries = entries[:3]
	got, collapsed, err = normalizeTocExtractEntries(entries)
	if err != nil {
		t.Fatalf("ordinary titles: %v", err)
	}
	if collapsed != 0 || !reflect.DeepEqual(got, entries) {
		t.Fatalf("ordinary titles changed: got %#v, want %#v", got, entries)
	}
}

func TestNormalizeTocExtractEntriesRequiresFullCollapsedRowCoverage(t *testing.T) {
	entries := []extract_toc.Entry{{
		Title: "One, 3. Two, 10. Three, 15. trailing note",
		Level: 2,
	}}
	if _, _, err := normalizeTocExtractEntries(entries); err == nil {
		t.Fatal("expected incomplete collapsed sequence to be rejected")
	}
}

func TestNormalizeTocExtractEntriesDoesNotSplitTwoPageTitle(t *testing.T) {
	entries := []extract_toc.Entry{{Title: "War, 1939. Peace, 1945.", Level: 2}}
	got, collapsed, err := normalizeTocExtractEntries(entries)
	if err != nil {
		t.Fatalf("normalizeTocExtractEntries: %v", err)
	}
	if collapsed != 0 || !reflect.DeepEqual(got, entries) {
		t.Fatalf("two-anchor title changed: %#v", got)
	}
}

func TestNormalizeColonPageAnchorOnlyRunsWithCollapsedCompanion(t *testing.T) {
	entries := []extract_toc.Entry{
		{Title: "A Real Subtitle: 1945", Level: 1},
		{Title: "One, 3. Two, 10. Three, 15.", Level: 2},
	}
	got, _, err := normalizeTocExtractEntries(entries)
	if err != nil {
		t.Fatalf("normalizeTocExtractEntries: %v", err)
	}
	if got[0].Title != "A Real Subtitle" || !reflect.DeepEqual(got[0].PrintedPageNumber, tocString("1945")) {
		t.Fatalf("companion anchor not normalized: %#v", got[0])
	}
}
