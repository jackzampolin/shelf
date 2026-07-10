package agents

import (
	"context"
	"strings"
	"testing"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestDeterministicAgentIDsAreBookScoped(t *testing.T) {
	ctx := context.Background()
	bookA := common.NewBookState("book-a")
	bookB := common.NewBookState("book-b")
	entry := &chapter_finder.EntryToFind{LevelName: "chapter", Identifier: "1"}

	chapterA := NewChapterFinderAgent(ctx, ChapterFinderConfig{Book: bookA, Entry: entry})
	chapterAAgain := NewChapterFinderAgent(ctx, ChapterFinderConfig{Book: bookA, Entry: entry})
	chapterB := NewChapterFinderAgent(ctx, ChapterFinderConfig{Book: bookB, Entry: entry})
	if chapterA.ID() != chapterAAgain.ID() {
		t.Fatalf("same-book chapter ID changed: %q != %q", chapterA.ID(), chapterAAgain.ID())
	}
	if chapterA.ID() == chapterB.ID() {
		t.Fatalf("cross-book chapter IDs collided: %q", chapterA.ID())
	}
	if !strings.Contains(chapterA.ID(), bookA.BookID) {
		t.Fatalf("chapter ID %q does not contain book scope %q", chapterA.ID(), bookA.BookID)
	}

	gap := &gap_investigator.GapInfo{StartPage: 10, EndPage: 20}
	gapA := NewGapInvestigatorAgent(ctx, GapInvestigatorConfig{Book: bookA, Gap: gap})
	gapB := NewGapInvestigatorAgent(ctx, GapInvestigatorConfig{Book: bookB, Gap: gap})
	if gapA.ID() == gapB.ID() {
		t.Fatalf("cross-book gap IDs collided: %q", gapA.ID())
	}
}
