package agents

import (
	"context"
	"testing"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestFreshFinalizeAgentIDsAreUnique(t *testing.T) {
	ctx := context.Background()
	bookA := common.NewBookState("book-a")
	bookB := common.NewBookState("book-b")
	entry := &chapter_finder.EntryToFind{LevelName: "chapter", Identifier: "1"}

	chapterA := NewChapterFinderAgent(ctx, ChapterFinderConfig{Book: bookA, Entry: entry})
	chapterAAgain := NewChapterFinderAgent(ctx, ChapterFinderConfig{Book: bookA, Entry: entry})
	chapterB := NewChapterFinderAgent(ctx, ChapterFinderConfig{Book: bookB, Entry: entry})
	if chapterA.ID() == chapterAAgain.ID() {
		t.Fatalf("fresh same-book chapter agents reused ID %q", chapterA.ID())
	}
	if chapterA.ID() == chapterB.ID() {
		t.Fatalf("cross-book chapter IDs collided: %q", chapterA.ID())
	}

	gap := &gap_investigator.GapInfo{StartPage: 10, EndPage: 20}
	gapA := NewGapInvestigatorAgent(ctx, GapInvestigatorConfig{Book: bookA, Gap: gap})
	gapAAgain := NewGapInvestigatorAgent(ctx, GapInvestigatorConfig{Book: bookA, Gap: gap})
	gapB := NewGapInvestigatorAgent(ctx, GapInvestigatorConfig{Book: bookB, Gap: gap})
	if gapA.ID() == gapAAgain.ID() {
		t.Fatalf("fresh same-book gap agents reused ID %q", gapA.ID())
	}
	if gapA.ID() == gapB.ID() {
		t.Fatalf("cross-book gap IDs collided: %q", gapA.ID())
	}
}
