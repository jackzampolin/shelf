package job

import (
	"context"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func newTocRecoveryJob(entries []*toc_entry_finder.TocEntry) (*Job, *common.MemoryStateStore) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	store.SetDoc("ToC", "toc-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableTocLink = true
	book.SetTocDocID("toc-1")
	book.SetOpState(common.OpTocExtract, false, true, false, 0)
	book.SetTocEntries(entries)

	return NewFromLoadResult(&common.LoadBookResult{
		Book:     book,
		TocDocID: "toc-1",
	}), store
}

func TestReconcileTocLinkRecoveryResetsFailedPendingEntries(t *testing.T) {
	j, store := newTocRecoveryJob([]*toc_entry_finder.TocEntry{
		{DocID: "entry-1", Title: "Chapter 1"},
		{DocID: "entry-2", Title: "Chapter 2"},
	})
	j.Book.SetOpState(common.OpTocLink, false, false, true, 3)
	j.Book.SetTocLinkProgress(13, 9)

	if err := j.reconcileTocLinkRecovery(context.Background()); err != nil {
		t.Fatal(err)
	}

	total, done := j.Book.GetTocLinkProgress()
	if total != 2 || done != 0 {
		t.Fatalf("ToC link progress = %d/%d, want 2/0", done, total)
	}

	state := j.Book.GetTocLinkState()
	if !state.CanStart() || state.IsFailed() || state.GetRetries() != 0 {
		t.Fatalf("ToC link state = canStart:%v failed:%v retries:%d, want reset with zero retries",
			state.CanStart(), state.IsFailed(), state.GetRetries())
	}

	tocDoc := store.GetDoc("ToC", "toc-1")
	if tocDoc["link_started"] != false || tocDoc["link_complete"] != false || tocDoc["link_failed"] != false || tocDoc["link_retries"] != 0 {
		t.Fatalf("persisted ToC link state = %#v, want reset", tocDoc)
	}
	bookDoc := store.GetDoc("Book", "book-1")
	if bookDoc["toc_link_entries_total"] != 2 || bookDoc["toc_link_entries_done"] != 0 {
		t.Fatalf("persisted ToC link progress = %#v, want total=2 done=0", bookDoc)
	}
}

func TestReconcileTocLinkRecoveryCompletesWhenNoPendingEntries(t *testing.T) {
	j, store := newTocRecoveryJob(nil)
	j.Book.SetOpState(common.OpTocLink, true, false, false, 2)
	j.Book.SetTocLinkProgress(32, 30)

	if err := j.reconcileTocLinkRecovery(context.Background()); err != nil {
		t.Fatal(err)
	}

	total, done := j.Book.GetTocLinkProgress()
	if total != 0 || done != 0 {
		t.Fatalf("ToC link progress = %d/%d, want 0/0", done, total)
	}

	state := j.Book.GetTocLinkState()
	if !state.IsComplete() || state.IsFailed() || state.GetRetries() != 0 {
		t.Fatalf("ToC link state = complete:%v failed:%v retries:%d, want complete with zero retries",
			state.IsComplete(), state.IsFailed(), state.GetRetries())
	}

	tocDoc := store.GetDoc("ToC", "toc-1")
	if tocDoc["link_started"] != false || tocDoc["link_complete"] != true || tocDoc["link_failed"] != false || tocDoc["link_retries"] != 0 {
		t.Fatalf("persisted ToC link state = %#v, want complete", tocDoc)
	}
}

func TestReconcileTocLinkRecoveryReopensCompleteWithPendingEntries(t *testing.T) {
	j, store := newTocRecoveryJob([]*toc_entry_finder.TocEntry{
		{DocID: "entry-1", Title: "Chapter 1"},
	})
	j.Book.SetOpState(common.OpTocLink, false, true, false, 0)
	j.Book.SetTocLinkProgress(32, 32)
	j.Book.SetOpState(common.OpTocFinalize, false, true, false, 0)
	j.Book.SetOpState(common.OpStructure, true, false, false, 0)

	if err := j.reconcileTocLinkRecovery(context.Background()); err != nil {
		t.Fatal(err)
	}

	total, done := j.Book.GetTocLinkProgress()
	if total != 1 || done != 0 {
		t.Fatalf("ToC link progress = %d/%d, want 1/0", done, total)
	}

	state := j.Book.GetTocLinkState()
	if !state.CanStart() || state.IsComplete() || state.IsFailed() {
		t.Fatalf("ToC link state = canStart:%v complete:%v failed:%v, want reopened",
			state.CanStart(), state.IsComplete(), state.IsFailed())
	}

	tocDoc := store.GetDoc("ToC", "toc-1")
	if tocDoc["link_started"] != false || tocDoc["link_complete"] != false || tocDoc["link_failed"] != false || tocDoc["link_retries"] != 0 {
		t.Fatalf("persisted ToC link state = %#v, want reopened", tocDoc)
	}
	if j.Book.TocFinalizeIsDone() || !j.Book.TocFinalizeCanStart() {
		t.Fatal("ToC finalize was not reset after reopening a completed link")
	}
	if j.Book.StructureIsDone() || !j.Book.StructureCanStart() {
		t.Fatal("structure was not reset after reopening a completed link")
	}
	if tocDoc["finalize_complete"] != false {
		t.Fatalf("persisted finalize state was not reset: %#v", tocDoc)
	}
	if bookDoc := store.GetDoc("Book", "book-1"); bookDoc["structure_complete"] != false {
		t.Fatalf("persisted structure state was not reset: %#v", bookDoc)
	}
}

func TestReconcileTocLinkRecoveryDeletesStaleLinkedEntryAgentStates(t *testing.T) {
	j, store := newTocRecoveryJob([]*toc_entry_finder.TocEntry{
		{DocID: "pending-entry", Title: "Chapter Pending"},
	})
	j.Book.SetOpState(common.OpTocLink, false, true, false, 0)

	store.SetDoc("AgentState", "linked-agent-state", map[string]any{
		"_bookID":      "book-1",
		"agent_id":     "linked-agent",
		"agent_type":   common.AgentTypeTocEntryFinder,
		"entry_doc_id": "linked-entry",
	})
	store.SetDoc("AgentState", "pending-agent-state", map[string]any{
		"_bookID":      "book-1",
		"agent_id":     "pending-agent",
		"agent_type":   common.AgentTypeTocEntryFinder,
		"entry_doc_id": "pending-entry",
	})
	j.Book.SetAgentState(&common.AgentState{
		DocID:      "linked-agent-state",
		AgentID:    "linked-agent",
		AgentType:  common.AgentTypeTocEntryFinder,
		EntryDocID: "linked-entry",
	})
	j.Book.SetAgentState(&common.AgentState{
		DocID:      "pending-agent-state",
		AgentID:    "pending-agent",
		AgentType:  common.AgentTypeTocEntryFinder,
		EntryDocID: "pending-entry",
	})

	if err := j.reconcileTocLinkRecovery(context.Background()); err != nil {
		t.Fatal(err)
	}

	if got := j.Book.GetAgentState(common.AgentTypeTocEntryFinder, "linked-entry"); got != nil {
		t.Fatalf("linked entry agent state still in memory: %#v", got)
	}
	if got := store.GetDoc("AgentState", "linked-agent-state"); got != nil {
		t.Fatalf("linked entry agent state still in store: %#v", got)
	}
	if got := j.Book.GetAgentState(common.AgentTypeTocEntryFinder, "pending-entry"); got == nil {
		t.Fatal("pending entry agent state was deleted")
	}
	if got := store.GetDoc("AgentState", "pending-agent-state"); got == nil {
		t.Fatal("pending entry agent state was deleted from store")
	}
}

func TestStartResumesStartedTocFinderWithSavedAgentState(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	store.SetDoc("ToC", "toc-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.TotalPages = ConsecutiveFrontMatterRequired
	book.OcrProviders = []string{"chandra-local"}
	book.TocProvider = "qwen-local"
	book.EnableOCR = true
	book.EnableMetadata = false
	book.EnableTocFinder = true
	book.EnableTocExtract = false
	book.EnableTocLink = false
	book.EnableTocFinalize = false
	book.EnableStructure = false
	book.SetTocDocID("toc-1")
	book.SetOpState(common.OpTocFinder, true, false, false, 0)
	book.SetAgentState(&common.AgentState{
		AgentID:      "agent-1",
		AgentType:    common.AgentTypeTocFinder,
		Complete:     false,
		MessagesJSON: "[]",
	})

	for pageNum := 1; pageNum <= ConsecutiveFrontMatterRequired; pageNum++ {
		page := book.GetOrCreatePage(pageNum)
		page.SetExtractDone(true)
		page.MarkOcrComplete("chandra-local", "OCR text for ToC finder.")
		page.SetOcrMarkdown("OCR text for ToC finder.")
	}

	j := NewFromLoadResult(&common.LoadBookResult{
		Book:     book,
		TocDocID: "toc-1",
	})
	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: defra.NewClient("http://127.0.0.1:1"),
	})

	units, err := j.Start(ctx)
	if err != nil {
		t.Fatalf("Start error: %v", err)
	}
	if len(units) == 0 {
		t.Fatal("Start returned no units for resumable ToC finder")
	}
	if len(units) != 1 {
		t.Fatalf("Start returned %d units, want 1 ToC finder resume unit", len(units))
	}
	info, ok := j.GetWorkUnit(units[0].ID)
	if !ok {
		t.Fatal("resume unit was not registered")
	}
	if info.UnitType != WorkUnitTypeTocFinder {
		t.Fatalf("resume unit type = %q, want %q", info.UnitType, WorkUnitTypeTocFinder)
	}
	if !j.Book.TocFinderIsStarted() {
		t.Fatal("ToC finder should remain started while resumed work is queued")
	}
	if j.Done() {
		t.Fatal("job should not be done while ToC finder resume unit is queued")
	}
}

func TestInterruptedOperationReopensWithoutConsumingRetry(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	store.SetDoc("ToC", "toc-1", map[string]any{})
	book := common.NewBookState("book-1")
	book.Store = store
	book.SetTocDocID("toc-1")
	j := NewFromLoadResult(&common.LoadBookResult{Book: book, TocDocID: "toc-1"})

	for _, op := range []common.OpType{
		common.OpMetadata,
		common.OpTocFinder,
		common.OpTocExtract,
		common.OpTocFinalize,
		common.OpStructure,
	} {
		book.SetOpState(op, true, false, false, 2)
		j.reopenInterruptedOperation(context.Background(), op)
		state := book.OpGetState(op)
		if !state.CanStart() || state.IsFailed() || state.GetRetries() != 2 {
			t.Fatalf("%s recovery = canStart:%v failed:%v retries:%d, want reopened with retries preserved",
				op, state.CanStart(), state.IsFailed(), state.GetRetries())
		}
	}

	bookDoc := store.GetDoc("Book", "book-1")
	if bookDoc["metadata_started"] != false || bookDoc["metadata_retries"] != 2 ||
		bookDoc["structure_started"] != false || bookDoc["structure_retries"] != 2 {
		t.Fatalf("persisted Book recovery state = %#v", bookDoc)
	}
	tocDoc := store.GetDoc("ToC", "toc-1")
	for _, prefix := range []string{"finder", "extract", "finalize"} {
		if tocDoc[prefix+"_started"] != false || tocDoc[prefix+"_retries"] != 2 {
			t.Fatalf("persisted ToC %s recovery state = %#v", prefix, tocDoc)
		}
	}
}

func TestStartMarksNoWorkCompleteJobDone(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableOCR = false
	book.EnableMetadata = false
	book.EnableTocFinder = false
	book.EnableTocExtract = false
	book.EnableTocLink = false
	book.EnableTocFinalize = false
	book.EnableStructure = false

	j := NewFromLoadResult(&common.LoadBookResult{Book: book})
	units, err := j.Start(context.Background())
	if err != nil {
		t.Fatalf("Start error: %v", err)
	}
	if len(units) != 0 {
		t.Fatalf("Start returned %d units, want 0", len(units))
	}
	if !j.Done() {
		t.Fatal("no-work complete job was not marked done")
	}
}
