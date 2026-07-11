package common

import (
	"context"
	"fmt"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
)

type flakyAgentStateStore struct {
	*MemoryStateStore
	remainingFailures int
	calls             int
}

type commitThenErrorAgentStateStore struct {
	*MemoryStateStore
	calls int
}

func (s *commitThenErrorAgentStateStore) UpsertWithVersion(ctx context.Context, collection string, filter, createInput, updateInput map[string]any) (defra.WriteResult, error) {
	s.calls++
	result, err := s.MemoryStateStore.UpsertWithVersion(ctx, collection, filter, createInput, updateInput)
	if err != nil {
		return result, err
	}
	return result, fmt.Errorf("defra server error (status 500): ")
}

func (s *flakyAgentStateStore) UpsertWithVersion(ctx context.Context, collection string, filter, createInput, updateInput map[string]any) (defra.WriteResult, error) {
	s.calls++
	if s.remainingFailures > 0 {
		s.remainingFailures--
		return defra.WriteResult{}, fmt.Errorf("defra server error (status 500)")
	}
	return s.MemoryStateStore.UpsertWithVersion(ctx, collection, filter, createInput, updateInput)
}

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
	store.SetDoc("Chapter", "ch1", map[string]any{"_bookID": "book1", "title": "Chapter 1"})
	store.SetDoc("Chapter", "ch2", map[string]any{"_bookID": "book1", "title": "Chapter 2"})
	store.SetDoc("Chapter", "ch3", map[string]any{"_bookID": "book2", "title": "Other Book"})

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

func TestBookState_DeleteAgentStateByKeysDeletesAllMatchingRows(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("AgentState", "as1", map[string]any{
		"_bookID":      "book1",
		"agent_type":   AgentTypeTocEntryFinder,
		"entry_doc_id": "entry1",
	})
	store.SetDoc("AgentState", "as2", map[string]any{
		"_bookID":      "book1",
		"agent_type":   AgentTypeTocEntryFinder,
		"entry_doc_id": "entry1",
	})
	store.SetDoc("AgentState", "as3", map[string]any{
		"_bookID":      "book1",
		"agent_type":   AgentTypeTocEntryFinder,
		"entry_doc_id": "entry2",
	})
	store.SetDoc("AgentState", "as4", map[string]any{
		"_bookID":      "book2",
		"agent_type":   AgentTypeTocEntryFinder,
		"entry_doc_id": "entry1",
	})

	book := NewBookState("book1")
	book.Store = store
	book.SetAgentState(&AgentState{
		AgentID:    "agent2",
		AgentType:  AgentTypeTocEntryFinder,
		EntryDocID: "entry1",
		DocID:      "as2",
	})

	if err := book.DeleteAgentStateByKeys(context.Background(), AgentTypeTocEntryFinder, "entry1"); err != nil {
		t.Fatalf("DeleteAgentStateByKeys error: %v", err)
	}

	if got := store.GetDoc("AgentState", "as1"); got != nil {
		t.Fatalf("matching duplicate as1 was not deleted: %#v", got)
	}
	if got := store.GetDoc("AgentState", "as2"); got != nil {
		t.Fatalf("matching duplicate as2 was not deleted: %#v", got)
	}
	if got := store.GetDoc("AgentState", "as3"); got == nil {
		t.Fatal("other entry state was deleted")
	}
	if got := store.GetDoc("AgentState", "as4"); got == nil {
		t.Fatal("other book state was deleted")
	}
	if got := book.GetAgentState(AgentTypeTocEntryFinder, "entry1"); got != nil {
		t.Fatalf("agent state still in memory: %#v", got)
	}
}

// TestBookState_DeleteAgentStatesForType tests the DeleteAgentStatesForType method.
func TestBookState_DeleteAgentStatesForType(t *testing.T) {
	store := NewMemoryStateStore()

	// Create some agent states
	store.SetDoc("AgentState", "as1", map[string]any{"_bookID": "book1", "agent_type": "toc_finder"})
	store.SetDoc("AgentState", "as2", map[string]any{"_bookID": "book1", "agent_type": "toc_finder"})
	store.SetDoc("AgentState", "as3", map[string]any{"_bookID": "book1", "agent_type": "chapter_finder"})

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
		"_bookID": "book1",
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
	store.SetDoc("TocEntry", "te1", map[string]any{"_tocID": "toc1", "title": "Entry 1"})
	store.SetDoc("TocEntry", "te2", map[string]any{"_tocID": "toc1", "title": "Entry 2"})
	store.SetDoc("TocEntry", "te3", map[string]any{"_tocID": "toc2", "title": "Other ToC"})

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
	store.SetDoc("ToC", "toc1", map[string]any{"_bookID": "book1"})

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

func TestPersistAgentStateScopesStableIDToBook(t *testing.T) {
	store := NewMemoryStateStore()
	bookA := NewBookState("book-a")
	bookA.Store = store
	bookB := NewBookState("book-b")
	bookB.Store = store

	stateA := &AgentState{AgentID: "chapter--1", AgentType: AgentTypeChapterFinder, EntryDocID: "entry-a"}
	stateB := &AgentState{AgentID: "chapter--1", AgentType: AgentTypeChapterFinder, EntryDocID: "entry-b"}
	if err := PersistAgentState(context.Background(), bookA, stateA); err != nil {
		t.Fatal(err)
	}
	if err := PersistAgentState(context.Background(), bookB, stateB); err != nil {
		t.Fatal(err)
	}
	if stateA.DocID == stateB.DocID {
		t.Fatalf("cross-book agent states shared DocID %q", stateA.DocID)
	}
	if got := len(store.docs["AgentState"]); got != 2 {
		t.Fatalf("AgentState count = %d, want 2", got)
	}
}

func TestPersistAgentStateUpdatesKnownCheckpointByDocID(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	store.SetDoc("AgentState", "state-1", map[string]any{
		"_bookID":      "book-1",
		"agent_id":     "agent-1",
		"agent_type":   AgentTypeTocEntryFinder,
		"entry_doc_id": "entry-1",
		"iteration":    0,
	})
	book := NewBookState("book-1")
	book.Store = store
	book.SetAgentState(&AgentState{
		DocID:      "state-1",
		AgentID:    "agent-1",
		AgentType:  AgentTypeTocEntryFinder,
		EntryDocID: "entry-1",
		Iteration:  0,
	})
	// If PersistAgentState accidentally uses upsert for a known checkpoint, this
	// injected error makes the regression deterministic.
	store.UpsertErr = fmt.Errorf("upsert update path must not be used")

	checkpoint := &AgentState{
		AgentID:      "agent-1",
		AgentType:    AgentTypeTocEntryFinder,
		EntryDocID:   "entry-1",
		Iteration:    2,
		MessagesJSON: `[{"role":"assistant","content":"checkpointed"}]`,
	}
	if err := PersistAgentState(context.Background(), book, checkpoint); err != nil {
		t.Fatal(err)
	}
	if checkpoint.DocID != "state-1" {
		t.Fatalf("checkpoint docID = %q, want state-1", checkpoint.DocID)
	}
	stored := store.GetDoc("AgentState", "state-1")
	if stored["iteration"] != 2 || stored["messages_json"] != checkpoint.MessagesJSON {
		t.Fatalf("stored checkpoint = %#v", stored)
	}
}

func TestPersistAgentStateRetriesTransientDefraWrite(t *testing.T) {
	store := &flakyAgentStateStore{
		MemoryStateStore:  NewMemoryStateStore(),
		remainingFailures: 1,
	}
	book := NewBookState("book-a")
	book.Store = store
	state := &AgentState{AgentID: "agent-a", AgentType: AgentTypeChapterFinder, EntryDocID: "entry-a"}

	if err := PersistAgentState(context.Background(), book, state); err != nil {
		t.Fatal(err)
	}
	if store.calls != 2 {
		t.Fatalf("upsert calls = %d, want one retry after transient 500", store.calls)
	}
	if state.DocID == "" {
		t.Fatal("successful retry did not capture AgentState DocID")
	}
}

func TestPersistAgentStateRecoversCommittedWriteAfterServerError(t *testing.T) {
	store := &commitThenErrorAgentStateStore{MemoryStateStore: NewMemoryStateStore()}
	book := NewBookState("book-a")
	book.Store = store
	state := &AgentState{
		AgentID:          "agent-a",
		AgentType:        AgentTypeChapterFinder,
		EntryDocID:       "entry-a",
		Iteration:        3,
		MessagesJSON:     "messages",
		PendingToolCalls: "pending",
		ToolResults:      "results",
		ResultJSON:       "result",
	}

	if err := PersistAgentState(context.Background(), book, state); err != nil {
		t.Fatal(err)
	}
	if store.calls != 1 {
		t.Fatalf("upsert calls = %d, want committed write recovered without retry", store.calls)
	}
	if state.DocID == "" {
		t.Fatal("read-after-error recovery did not capture AgentState DocID")
	}
}

func TestPersistAgentStateDoesNotAcceptStaleRowAfterServerError(t *testing.T) {
	memory := NewMemoryStateStore()
	memory.SetDoc("AgentState", "old", map[string]any{
		"_bookID":            "book-a",
		"agent_id":           "agent-a",
		"agent_type":         AgentTypeChapterFinder,
		"entry_doc_id":       "entry-a",
		"iteration":          0,
		"complete":           false,
		"messages_json":      "old",
		"pending_tool_calls": "",
		"tool_results":       "",
		"result_json":        "",
	})
	store := &flakyAgentStateStore{MemoryStateStore: memory, remainingFailures: 1}
	book := NewBookState("book-a")
	book.Store = store
	state := &AgentState{
		AgentID:      "agent-a",
		AgentType:    AgentTypeChapterFinder,
		EntryDocID:   "entry-a",
		Iteration:    1,
		MessagesJSON: "new",
	}

	if err := PersistAgentState(context.Background(), book, state); err != nil {
		t.Fatal(err)
	}
	if store.calls != 2 {
		t.Fatalf("upsert calls = %d, want retry after stale read-back", store.calls)
	}
}
