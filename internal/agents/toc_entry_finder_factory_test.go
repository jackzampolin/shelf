package agents

import (
	"context"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestNewTocEntryFinderAgentGeneratesUniqueIDs(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 100
	entry := &toc_entry_finder.TocEntry{
		DocID:       "entry-1",
		EntryNumber: "7",
		LevelName:   "chapter",
		Title:       "Winter in Algiers",
	}

	first := NewTocEntryFinderAgent(context.Background(), TocEntryFinderConfig{
		Book:  book,
		Entry: entry,
	})
	second := NewTocEntryFinderAgent(context.Background(), TocEntryFinderConfig{
		Book:  book,
		Entry: entry,
	})

	if first.ID() == "" || second.ID() == "" {
		t.Fatal("expected generated agent IDs")
	}
	if first.ID() == second.ID() {
		t.Fatalf("agent IDs should be unique across attempts, both were %q", first.ID())
	}
}
