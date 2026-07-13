package job

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestNormalizeSequenceIdentifier(t *testing.T) {
	for _, value := range []string{"1", "I", "one", "ONE"} {
		if got := normalizeSequenceIdentifier(value); got != "1" {
			t.Fatalf("normalizeSequenceIdentifier(%q) = %q, want 1", value, got)
		}
	}
	for _, value := range []string{"21", "XXI", "twenty-one", "TWENTY ONE"} {
		if got := normalizeSequenceIdentifier(value); got != "21" {
			t.Fatalf("normalizeSequenceIdentifier(%q) = %q, want 21", value, got)
		}
	}
}

func TestGenerateEntriesToFindNormalizesExistingIdentifiers(t *testing.T) {
	page22 := 22
	book := common.NewBookState("book-1")
	book.SetLinkedEntries([]*common.LinkedTocEntry{
		{EntryNumber: "ONE", LevelName: "chapter", ActualPage: &page22},
	})
	book.SetBodyRange(1, 100)
	book.SetFinalizePatternResult(&common.FinalizePatternResult{
		Patterns: []common.DiscoveredPattern{
			{LevelName: "chapter", RangeStart: "1", RangeEnd: "2", Level: 1},
		},
	})
	job := NewFromLoadResult(&common.LoadBookResult{Book: book, TocDocID: "toc-1"})

	job.generateEntriesToFind(context.Background())

	entries := book.GetEntriesToFind()
	if len(entries) != 1 || entries[0].Identifier != "2" {
		t.Fatalf("entries to find = %#v, want only chapter 2", entries)
	}
}

func TestGenerateEntriesToFindSkipsAmbiguousEmptyLevelDuplicate(t *testing.T) {
	page22 := 22
	book := common.NewBookState("book-1")
	book.SetLinkedEntries([]*common.LinkedTocEntry{
		{EntryNumber: "ONE", LevelName: "chapter", ActualPage: &page22},
	})
	book.SetBodyRange(1, 100)
	book.SetFinalizePatternResult(&common.FinalizePatternResult{
		Patterns: []common.DiscoveredPattern{
			{RangeStart: "1", RangeEnd: "1", Level: 1},
		},
	})
	job := NewFromLoadResult(&common.LoadBookResult{Book: book, TocDocID: "toc-1"})

	job.generateEntriesToFind(context.Background())

	if entries := book.GetEntriesToFind(); len(entries) != 0 {
		t.Fatalf("entries to find = %#v, want no duplicate chapter 1", entries)
	}
}

func TestGenerateEntriesToFindSkipsEmptyIdentifier(t *testing.T) {
	book := common.NewBookState("book-1")
	book.SetBodyRange(1, 100)
	book.SetFinalizePatternResult(&common.FinalizePatternResult{
		Patterns: []common.DiscoveredPattern{
			{PatternType: "sequential", RangeStart: "", RangeEnd: ""},
		},
	})
	job := NewFromLoadResult(&common.LoadBookResult{Book: book, TocDocID: "toc-1"})

	job.generateEntriesToFind(context.Background())

	if entries := book.GetEntriesToFind(); len(entries) != 0 {
		t.Fatalf("entries to find = %#v, want no empty discovery key", entries)
	}
}

func TestSanitizeDiscoveredPatternsRejectsMalformedControlData(t *testing.T) {
	valid := common.DiscoveredPattern{
		PatternType: "sequential", LevelName: "chapter", HeadingFormat: "CHAPTER {n}",
		RangeStart: "1", RangeEnd: "3", Level: 2, Reasoning: "observed global sequence",
	}
	patterns := []common.DiscoveredPattern{
		valid,
		{PatternType: "sequential", RangeStart: "1", Reasoning: "model emitted partial fields"},
		{PatternType: "named", LevelName: "chapter", HeadingFormat: "{n}", RangeStart: "A", RangeEnd: "F", Level: 2, Reasoning: "unsupported plan"},
		{PatternType: "sequential", LevelName: "chapter", HeadingFormat: "CHAPTER", RangeStart: "1", RangeEnd: "3", Level: 2, Reasoning: "missing placeholder"},
		{PatternType: "sequential", LevelName: "chapter", HeadingFormat: "CHAPTER {n}", RangeStart: "3", RangeEnd: "1", Level: 2, Reasoning: "reversed"},
		{PatternType: "sequential", LevelName: "chapter", HeadingFormat: "CHAPTER {n}", RangeStart: "1", RangeEnd: "501", Level: 2, Reasoning: "unbounded"},
		{PatternType: "sequential", LevelName: "section", HeadingFormat: "{n}", RangeStart: "I", RangeEnd: "VII", Level: 3, Reasoning: "Roman numerals restart in every chapter"},
		{PatternType: "sequential", LevelName: "section", HeadingFormat: " ({n}). ", RangeStart: "1", RangeEnd: "7", Level: 3, Reasoning: "punctuation does not make a global identity"},
	}

	got := sanitizeDiscoveredPatterns(patterns)
	if len(got) != 1 || got[0] != valid {
		t.Fatalf("sanitized patterns = %#v, want only valid pattern", got)
	}
}

func TestHasDiscoveryHeadingAnchor(t *testing.T) {
	for _, format := range []string{"CHAPTER {n}", "Part {n}", "Appendix-{n}"} {
		if !hasDiscoveryHeadingAnchor(format) {
			t.Fatalf("hasDiscoveryHeadingAnchor(%q) = false, want true", format)
		}
	}
	for _, format := range []string{"{n}", " {n}. ", "({n})", "§ {n}"} {
		if hasDiscoveryHeadingAnchor(format) {
			t.Fatalf("hasDiscoveryHeadingAnchor(%q) = true, want false", format)
		}
	}
}

func TestSanitizeDiscoveredPatternsRequiresCandidateSupport(t *testing.T) {
	chapterPattern := common.DiscoveredPattern{
		PatternType: "sequential", LevelName: "chapter", HeadingFormat: "CHAPTER {n}",
		RangeStart: "1", RangeEnd: "3", Level: 2, Reasoning: "observed global sequence",
	}
	bareRomanCandidates := []*candidateHeading{
		{PageNum: 23, Text: "I", Level: 3},
		{PageNum: 29, Text: "II", Level: 3},
	}
	if got := sanitizeDiscoveredPatternsWithCandidates([]common.DiscoveredPattern{chapterPattern}, bareRomanCandidates); len(got) != 0 {
		t.Fatalf("invented CHAPTER anchor accepted: %#v", got)
	}

	chapterCandidates := []*candidateHeading{
		{PageNum: 15, Text: "CHAPTER 1", Level: 2},
		{PageNum: 30, Text: "Chapter 2: War", Level: 2},
	}
	if got := sanitizeDiscoveredPatternsWithCandidates([]common.DiscoveredPattern{chapterPattern}, chapterCandidates); len(got) != 1 {
		t.Fatalf("source-supported chapter pattern rejected: %#v", got)
	}
}

func TestSanitizeDiscoveredPatternsRejectsRestartingCandidateSequence(t *testing.T) {
	sectionPattern := common.DiscoveredPattern{
		PatternType: "sequential", LevelName: "section", HeadingFormat: "Section {n}",
		RangeStart: "I", RangeEnd: "II", Level: 3, Reasoning: "sections inside chapters",
	}
	candidates := []*candidateHeading{
		{PageNum: 23, Text: "Section I", Level: 3},
		{PageNum: 29, Text: "Section II", Level: 3},
		{PageNum: 44, Text: "Section I", Level: 3},
		{PageNum: 50, Text: "Section II", Level: 3},
	}

	if got := sanitizeDiscoveredPatternsWithCandidates([]common.DiscoveredPattern{sectionPattern}, candidates); len(got) != 0 {
		t.Fatalf("locally restarting section pattern accepted: %#v", got)
	}
}

func TestSanitizeDiscoveredPatternsAcceptsRomanSequence(t *testing.T) {
	pattern := common.DiscoveredPattern{
		PatternType: " sequential ", LevelName: " part ", HeadingFormat: "PART {n} ",
		RangeStart: " I ", RangeEnd: " VI ", Level: 1, Reasoning: " observed ",
	}

	got := sanitizeDiscoveredPatterns([]common.DiscoveredPattern{pattern})
	if len(got) != 1 || got[0].RangeStart != "I" || got[0].RangeEnd != "VI" || got[0].LevelName != "part" {
		t.Fatalf("sanitized Roman pattern = %#v", got)
	}
}

func TestDiscoveredEntryAlreadyLinked(t *testing.T) {
	page22 := 22
	existing := []*common.LinkedTocEntry{
		{EntryNumber: "ONE", LevelName: "chapter", ActualPage: &page22},
	}

	if !discoveredEntryAlreadyLinked(existing, &common.EntryToFind{Identifier: "1"}, 22) {
		t.Fatal("empty-level Arabic duplicate should match spelled-out linked chapter")
	}
	if !discoveredEntryAlreadyLinked(existing, &common.EntryToFind{Identifier: "I", LevelName: "chapter"}, 22) {
		t.Fatal("Roman duplicate should match spelled-out linked chapter")
	}
	if discoveredEntryAlreadyLinked(existing, &common.EntryToFind{Identifier: "2", LevelName: "chapter"}, 22) {
		t.Fatal("different chapter number must not be treated as duplicate")
	}
	if discoveredEntryAlreadyLinked(existing, &common.EntryToFind{Identifier: "1", LevelName: "part"}, 22) {
		t.Fatal("known different hierarchy levels may legitimately share a source page")
	}
	if discoveredEntryAlreadyLinked(existing, &common.EntryToFind{Identifier: "1", LevelName: "chapter"}, 23) {
		t.Fatal("same identifier on a different source page is not the same link")
	}
}
