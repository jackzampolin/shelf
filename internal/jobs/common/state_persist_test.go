package common

import (
	"context"
	"testing"
)

// TestBookState_PersistBookStatus tests the PersistBookStatus method.
func TestBookState_PersistBookStatus(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book1", map[string]any{"title": "Test"})

	book := NewBookState("book1")
	book.Store = store

	cid, err := book.PersistBookStatus(context.Background(), "processing")
	if err != nil {
		t.Fatalf("PersistBookStatus error: %v", err)
	}
	if cid == "" {
		t.Error("PersistBookStatus returned empty CID")
	}

	// Verify DB was updated
	doc := store.GetDoc("Book", "book1")
	if doc["status"] != "processing" {
		t.Errorf("status = %v, want 'processing'", doc["status"])
	}

	// Verify CID was tracked
	if book.GetBookCID() != cid {
		t.Errorf("GetBookCID() = %v, want %v", book.GetBookCID(), cid)
	}
}

// TestBookState_PersistOpState tests the PersistOpState method.
func TestBookState_PersistOpState(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book1", map[string]any{})

	book := NewBookState("book1")
	book.Store = store

	// Start an operation
	if err := book.OpStart(OpMetadata); err != nil {
		t.Fatalf("OpStart error: %v", err)
	}

	// Persist the state
	if err := book.PersistOpState(context.Background(), OpMetadata); err != nil {
		t.Fatalf("PersistOpState error: %v", err)
	}

	// Verify DB was updated
	doc := store.GetDoc("Book", "book1")
	if doc["metadata_started"] != true {
		t.Errorf("metadata_started = %v, want true", doc["metadata_started"])
	}
}

// TestBookState_PersistStructurePhase tests the PersistStructurePhase method.
func TestBookState_PersistStructurePhase(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book1", map[string]any{})

	book := NewBookState("book1")
	book.Store = store
	book.SetStructurePhase("extract")
	book.SetStructureProgress(10, 5, 2, 1)

	if err := book.PersistStructurePhase(context.Background()); err != nil {
		t.Fatalf("PersistStructurePhase error: %v", err)
	}

	doc := store.GetDoc("Book", "book1")
	if doc["structure_phase"] != "extract" {
		t.Errorf("structure_phase = %v, want 'extract'", doc["structure_phase"])
	}
	if doc["structure_chapters_total"] != 10 {
		t.Errorf("structure_chapters_total = %v, want 10", doc["structure_chapters_total"])
	}
	if doc["structure_chapters_extracted"] != 5 {
		t.Errorf("structure_chapters_extracted = %v, want 5", doc["structure_chapters_extracted"])
	}
}

// TestBookState_DeleteAllChapters tests the DeleteAllChapters method.
func TestBookState_DeleteAllChapters(t *testing.T) {
	store := NewMemoryStateStore()

	// Create some chapters
	store.SetDoc("Chapter", "ch1", map[string]any{"book_id": "book1", "title": "Chapter 1"})
	store.SetDoc("Chapter", "ch2", map[string]any{"book_id": "book1", "title": "Chapter 2"})
	store.SetDoc("Chapter", "ch3", map[string]any{"book_id": "book2", "title": "Other Book"})

	book := NewBookState("book1")
	book.Store = store
	book.SetStructureChapters([]*ChapterState{
		{EntryID: "e1", DocID: "ch1"},
		{EntryID: "e2", DocID: "ch2"},
	})

	if err := book.DeleteAllChapters(context.Background()); err != nil {
		t.Fatalf("DeleteAllChapters error: %v", err)
	}

	// Verify chapters for book1 were deleted
	if store.GetDoc("Chapter", "ch1") != nil {
		t.Error("Chapter ch1 should have been deleted")
	}
	if store.GetDoc("Chapter", "ch2") != nil {
		t.Error("Chapter ch2 should have been deleted")
	}

	// Verify chapter for other book is still there
	if store.GetDoc("Chapter", "ch3") == nil {
		t.Error("Chapter ch3 should not have been deleted")
	}

	// Verify memory was cleared
	if book.GetStructureChapters() != nil {
		t.Error("structureChapters should be nil")
	}
}

// TestBookState_PersistNewAgentState tests the PersistNewAgentState method.
func TestBookState_PersistNewAgentState(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book1")
	book.Store = store

	state := &AgentState{
		AgentID:   "agent-123",
		AgentType: AgentTypeTocFinder,
		Iteration: 1,
	}

	if err := book.PersistNewAgentState(context.Background(), state); err != nil {
		t.Fatalf("PersistNewAgentState error: %v", err)
	}

	// Verify DocID was set
	if state.DocID == "" {
		t.Error("AgentState.DocID should be set")
	}

	// Verify agent is in memory
	retrieved := book.GetAgentState(AgentTypeTocFinder, "")
	if retrieved == nil {
		t.Error("Agent state should be in memory")
	}
	if retrieved.AgentID != "agent-123" {
		t.Errorf("AgentID = %v, want 'agent-123'", retrieved.AgentID)
	}
}

// TestBookState_DeleteAgentStatesForType tests the DeleteAgentStatesForType method.
func TestBookState_DeleteAgentStatesForType(t *testing.T) {
	store := NewMemoryStateStore()

	// Create some agent states
	store.SetDoc("AgentState", "as1", map[string]any{"book_id": "book1", "agent_type": "toc_finder"})
	store.SetDoc("AgentState", "as2", map[string]any{"book_id": "book1", "agent_type": "toc_finder"})
	store.SetDoc("AgentState", "as3", map[string]any{"book_id": "book1", "agent_type": "chapter_finder"})

	book := NewBookState("book1")
	book.Store = store
	book.SetAgentState(&AgentState{AgentType: AgentTypeTocFinder, AgentID: "a1", DocID: "as1"})
	book.SetAgentState(&AgentState{AgentType: AgentTypeTocFinder, AgentID: "a2", DocID: "as2", EntryDocID: "e1"})
	book.SetAgentState(&AgentState{AgentType: AgentTypeChapterFinder, AgentID: "a3", DocID: "as3"})

	if err := book.DeleteAgentStatesForType(context.Background(), AgentTypeTocFinder); err != nil {
		t.Fatalf("DeleteAgentStatesForType error: %v", err)
	}

	// Verify toc_finder states were deleted from DB
	if store.GetDoc("AgentState", "as1") != nil {
		t.Error("AgentState as1 should have been deleted")
	}
	if store.GetDoc("AgentState", "as2") != nil {
		t.Error("AgentState as2 should have been deleted")
	}

	// Verify chapter_finder is still there
	if store.GetDoc("AgentState", "as3") == nil {
		t.Error("AgentState as3 should not have been deleted")
	}

	// Verify memory was cleared for toc_finder
	if book.GetAgentState(AgentTypeTocFinder, "") != nil {
		t.Error("toc_finder agent should be cleared from memory")
	}
	if book.GetAgentState(AgentTypeTocFinder, "e1") != nil {
		t.Error("toc_finder:e1 agent should be cleared from memory")
	}
	if book.GetAgentState(AgentTypeChapterFinder, "") == nil {
		t.Error("chapter_finder agent should still be in memory")
	}
}

// TestBookState_PersistTocRecord tests the PersistTocRecord method.
func TestBookState_PersistTocRecord(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book1")
	book.Store = store

	doc := map[string]any{
		"book_id": "book1",
	}

	docID, err := book.PersistTocRecord(context.Background(), doc)
	if err != nil {
		t.Fatalf("PersistTocRecord error: %v", err)
	}
	if docID == "" {
		t.Error("PersistTocRecord returned empty DocID")
	}

	// Verify DocID was stored
	if book.TocDocID() != docID {
		t.Errorf("TocDocID() = %v, want %v", book.TocDocID(), docID)
	}

	// Verify ToC CID is tracked
	if book.GetTocCID() == "" {
		t.Error("ToC CID should be set")
	}
}

// TestBookState_DeleteAllTocEntries tests the DeleteAllTocEntries method.
func TestBookState_DeleteAllTocEntries(t *testing.T) {
	store := NewMemoryStateStore()

	// Create some ToC entries
	store.SetDoc("TocEntry", "te1", map[string]any{"toc_id": "toc1", "title": "Entry 1"})
	store.SetDoc("TocEntry", "te2", map[string]any{"toc_id": "toc1", "title": "Entry 2"})
	store.SetDoc("TocEntry", "te3", map[string]any{"toc_id": "toc2", "title": "Other ToC"})

	book := NewBookState("book1")
	book.Store = store
	book.SetTocDocID("toc1")

	if err := book.DeleteAllTocEntries(context.Background(), "toc1"); err != nil {
		t.Fatalf("DeleteAllTocEntries error: %v", err)
	}

	// Verify entries for toc1 were deleted
	if store.GetDoc("TocEntry", "te1") != nil {
		t.Error("TocEntry te1 should have been deleted")
	}
	if store.GetDoc("TocEntry", "te2") != nil {
		t.Error("TocEntry te2 should have been deleted")
	}

	// Verify entry for other ToC is still there
	if store.GetDoc("TocEntry", "te3") == nil {
		t.Error("TocEntry te3 should not have been deleted")
	}
}

// TestBookState_PersistFinalizePhase tests the PersistFinalizePhase method.
func TestBookState_PersistFinalizePhase(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("ToC", "toc1", map[string]any{"book_id": "book1"})

	book := NewBookState("book1")
	book.Store = store
	book.SetTocDocID("toc1")

	cid, err := book.PersistFinalizePhase(context.Background(), "discover")
	if err != nil {
		t.Fatalf("PersistFinalizePhase error: %v", err)
	}
	if cid == "" {
		t.Error("PersistFinalizePhase returned empty CID")
	}

	// Verify DB was updated
	doc := store.GetDoc("ToC", "toc1")
	if doc["finalize_phase"] != "discover" {
		t.Errorf("finalize_phase = %v, want 'discover'", doc["finalize_phase"])
	}

	// Verify memory was updated
	if book.GetFinalizePhase() != "discover" {
		t.Errorf("GetFinalizePhase() = %v, want 'discover'", book.GetFinalizePhase())
	}
}
