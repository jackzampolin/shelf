package common

import (
	"reflect"
	"testing"
)

func TestSelectAgentStatesForResumeDeduplicatesLogicalAgents(t *testing.T) {
	states := []*AgentState{
		{DocID: "doc-b", AgentID: "agent-b", AgentType: AgentTypeTocEntryFinder, EntryDocID: "entry-1", Iteration: 1, MessagesJSON: "short"},
		{DocID: "doc-a", AgentID: "agent-a", AgentType: AgentTypeTocEntryFinder, EntryDocID: "entry-1", Iteration: 2, MessagesJSON: "advanced"},
		{DocID: "doc-c", AgentID: "agent-c", AgentType: AgentTypeTocEntryFinder, EntryDocID: "entry-1", Iteration: 2, MessagesJSON: "x"},
		{DocID: "doc-complete", AgentID: "done", AgentType: AgentTypeTocFinder, Complete: true},
		{DocID: "doc-gap", AgentID: "gap", AgentType: AgentTypeGapInvestigator, EntryDocID: "gap-1"},
	}

	resume, stale := selectAgentStatesForResume(states)
	if len(resume) != 2 {
		t.Fatalf("resume states = %d, want 2", len(resume))
	}
	if resume[0].DocID != "doc-gap" || resume[1].DocID != "doc-a" {
		t.Fatalf("selected unexpected resume states: %q, %q", resume[0].DocID, resume[1].DocID)
	}
	wantStale := []string{"doc-b", "doc-c", "doc-complete"}
	if !reflect.DeepEqual(stale, wantStale) {
		t.Fatalf("stale = %v, want %v", stale, wantStale)
	}
}

func TestSelectAgentStatesForResumeUsesStableTieBreak(t *testing.T) {
	states := []*AgentState{
		{DocID: "doc-z", AgentType: AgentTypeChapterFinder, EntryDocID: "chapter-1", MessagesJSON: "same"},
		{DocID: "doc-a", AgentType: AgentTypeChapterFinder, EntryDocID: "chapter-1", MessagesJSON: "same"},
	}

	resume, stale := selectAgentStatesForResume(states)
	if len(resume) != 1 || resume[0].DocID != "doc-a" {
		t.Fatalf("resume = %+v, want doc-a", resume)
	}
	if !reflect.DeepEqual(stale, []string{"doc-z"}) {
		t.Fatalf("stale = %v, want [doc-z]", stale)
	}
}
