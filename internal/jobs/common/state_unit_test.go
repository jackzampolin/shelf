package common

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
)

// TestOpRegistry_AllOpsRegistered verifies that every OpType in AllOpTypes is in the registry.
func TestOpRegistry_AllOpsRegistered(t *testing.T) {
	for _, op := range AllOpTypes {
		if _, ok := OpRegistry[op]; !ok {
			t.Errorf("OpType %s not found in OpRegistry", op)
		}
	}
}

// TestOpRegistry_ConfigFields verifies that all OpConfig entries have required fields.
func TestOpRegistry_ConfigFields(t *testing.T) {
	for op, cfg := range OpRegistry {
		if cfg.Collection == "" {
			t.Errorf("OpRegistry[%s].Collection is empty", op)
		}
		if cfg.FieldPrefix == "" {
			t.Errorf("OpRegistry[%s].FieldPrefix is empty", op)
		}
		if cfg.DocIDSource == nil {
			t.Errorf("OpRegistry[%s].DocIDSource is nil", op)
		}
	}
}

// TestGenericOps_AllOperations tests the 9 generic methods for every operation type.
func TestGenericOps_AllOperations(t *testing.T) {
	for _, op := range AllOpTypes {
		t.Run(string(op), func(t *testing.T) {
			book := NewBookState("test-book")

			// CanStart: should be true initially
			if !book.OpCanStart(op) {
				t.Errorf("OpCanStart(%s) = false, want true (initial)", op)
			}

			// IsStarted: should be false initially
			if book.OpIsStarted(op) {
				t.Errorf("OpIsStarted(%s) = true, want false (initial)", op)
			}

			// IsDone: should be false initially
			if book.OpIsDone(op) {
				t.Errorf("OpIsDone(%s) = true, want false (initial)", op)
			}

			// IsComplete: should be false initially
			if book.OpIsComplete(op) {
				t.Errorf("OpIsComplete(%s) = true, want false (initial)", op)
			}

			// GetState: should be not-started
			state := book.OpGetState(op)
			if state.IsStarted() {
				t.Errorf("OpGetState(%s).IsStarted() = true, want false", op)
			}

			// Start
			if err := book.OpStart(op); err != nil {
				t.Errorf("OpStart(%s) error = %v", op, err)
			}
			if !book.OpIsStarted(op) {
				t.Errorf("OpIsStarted(%s) = false after Start", op)
			}
			if book.OpCanStart(op) {
				t.Errorf("OpCanStart(%s) = true after Start", op)
			}

			// Complete
			book.OpComplete(op)
			if !book.OpIsDone(op) {
				t.Errorf("OpIsDone(%s) = false after Complete", op)
			}
			if !book.OpIsComplete(op) {
				t.Errorf("OpIsComplete(%s) = false after Complete", op)
			}

			// Reset
			book.OpReset(op)
			if !book.OpCanStart(op) {
				t.Errorf("OpCanStart(%s) = false after Reset", op)
			}
			if book.OpIsDone(op) {
				t.Errorf("OpIsDone(%s) = true after Reset", op)
			}
		})
	}
}

// TestGenericOps_FailWithRetries tests the fail/retry mechanism via generic methods.
func TestGenericOps_FailWithRetries(t *testing.T) {
	book := NewBookState("test-book")
	op := OpMetadata

	_ = book.OpStart(op)

	// First fail - should allow retry
	permFailed := book.OpFail(op, 3)
	if permFailed {
		t.Error("should not be permanently failed after first fail")
	}
	if !book.OpCanStart(op) {
		t.Error("should be able to start after fail with retries remaining")
	}

	// Second fail
	_ = book.OpStart(op)
	permFailed = book.OpFail(op, 3)
	if permFailed {
		t.Error("should not be permanently failed after second fail")
	}

	// Third fail - should be permanent
	_ = book.OpStart(op)
	permFailed = book.OpFail(op, 3)
	if !permFailed {
		t.Error("should be permanently failed after third fail")
	}
	if !book.OpIsDone(op) {
		t.Error("should be done after permanent fail")
	}
	if book.OpIsComplete(op) {
		t.Error("should not be complete after fail")
	}
}

// TestGenericOps_DoubleStart tests that starting an already-started operation returns error.
func TestGenericOps_DoubleStart(t *testing.T) {
	book := NewBookState("test-book")
	op := OpTocFinder

	if err := book.OpStart(op); err != nil {
		t.Fatalf("first OpStart error = %v", err)
	}

	err := book.OpStart(op)
	if err == nil {
		t.Error("second OpStart should return error")
	}
}

// TestGenericOps_UnknownOp tests that unknown operations return errors.
func TestGenericOps_UnknownOp(t *testing.T) {
	book := NewBookState("test-book")
	err := book.OpStart(OpType("nonexistent"))
	if err == nil {
		t.Error("OpStart with unknown op should return error")
	}
}

// TestSetOpState tests setting operation state from DB values.
func TestSetOpState(t *testing.T) {
	book := NewBookState("test-book")

	// Set as complete with 2 retries
	book.SetOpState(OpMetadata, false, true, false, 2)
	if !book.OpIsComplete(OpMetadata) {
		t.Error("should be complete after SetOpState(complete=true)")
	}
	state := book.OpGetState(OpMetadata)
	if state.GetRetries() != 2 {
		t.Errorf("retries = %d, want 2", state.GetRetries())
	}

	// Set as failed
	book.SetOpState(OpTocFinder, false, false, true, 3)
	if !book.OpIsDone(OpTocFinder) {
		t.Error("should be done after SetOpState(failed=true)")
	}
	if book.OpIsComplete(OpTocFinder) {
		t.Error("should not be complete when failed")
	}

	// Set as in-progress
	book.SetOpState(OpTocExtract, true, false, false, 0)
	if !book.OpIsStarted(OpTocExtract) {
		t.Error("should be started after SetOpState(started=true)")
	}
}

// TestTocDocID tests the TocDocID getter/setter.
func TestTocDocID(t *testing.T) {
	book := NewBookState("test-book")

	if book.TocDocID() != "" {
		t.Error("TocDocID should be empty initially")
	}

	book.SetTocDocID("toc-123")
	if book.TocDocID() != "toc-123" {
		t.Errorf("TocDocID = %s, want toc-123", book.TocDocID())
	}
}

// TestPersistOpState_WithMemoryStore tests persisting operation state via MemoryStateStore.
func TestPersistOpState_WithMemoryStore(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("test-book")
	book.Store = store

	// Start and complete metadata
	_ = book.OpStart(OpMetadata)
	book.OpComplete(OpMetadata)

	ctx := context.Background()
	if err := PersistOpState(ctx, book, OpMetadata); err != nil {
		t.Fatalf("PersistOpState error = %v", err)
	}

	// Verify the store received the write
	if store.WriteCount() != 1 {
		t.Errorf("WriteCount = %d, want 1", store.WriteCount())
	}

	writes := store.GetWrites()
	if writes[0].Collection != "Book" {
		t.Errorf("Collection = %s, want Book", writes[0].Collection)
	}
	if writes[0].DocID != book.BookID {
		t.Errorf("DocID = %s, want %s", writes[0].DocID, book.BookID)
	}

	doc := writes[0].Document
	if started, ok := doc["metadata_started"].(bool); !ok || started {
		t.Errorf("metadata_started = %v, want false", doc["metadata_started"])
	}
	if complete, ok := doc["metadata_complete"].(bool); !ok || !complete {
		t.Errorf("metadata_complete = %v, want true", doc["metadata_complete"])
	}
}

// TestPersistOpState_WithMemoryStore_StartedOnly tests started-only persistence.
func TestPersistOpState_WithMemoryStore_StartedOnly(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("test-book")
	book.Store = store

	_ = book.OpStart(OpMetadata)

	ctx := context.Background()
	if err := PersistOpState(ctx, book, OpMetadata); err != nil {
		t.Fatalf("PersistOpState error = %v", err)
	}

	if store.WriteCount() != 1 {
		t.Errorf("WriteCount = %d, want 1", store.WriteCount())
	}

	writes := store.GetWrites()
	doc := writes[0].Document
	if started, ok := doc["metadata_started"].(bool); !ok || !started {
		t.Errorf("metadata_started = %v, want true", doc["metadata_started"])
	}
}

// TestPersistOpState_TocOperation tests persisting a ToC operation state.
func TestPersistOpState_TocOperation(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("test-book")
	book.Store = store
	book.SetTocDocID("toc-456")

	_ = book.OpStart(OpTocFinder)

	ctx := context.Background()
	if err := PersistOpState(ctx, book, OpTocFinder); err != nil {
		t.Fatalf("PersistOpState error = %v", err)
	}

	writes := store.GetWrites()
	if len(writes) != 1 {
		t.Fatalf("WriteCount = %d, want 1", len(writes))
	}
	if writes[0].Collection != "ToC" {
		t.Errorf("Collection = %s, want ToC", writes[0].Collection)
	}
	if writes[0].DocID != "toc-456" {
		t.Errorf("DocID = %s, want toc-456", writes[0].DocID)
	}
}

// TestPersistOpState_EmptyDocID tests that persist is a no-op when DocID is empty.
func TestPersistOpState_EmptyDocID(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("test-book")
	book.Store = store
	// Don't set TocDocID - it should be empty

	ctx := context.Background()
	if err := PersistOpState(ctx, book, OpTocFinder); err != nil {
		t.Fatalf("PersistOpState error = %v", err)
	}

	// Should not have written anything since DocID is empty
	if store.WriteCount() != 0 {
		t.Errorf("WriteCount = %d, want 0 (empty docID)", store.WriteCount())
	}
}

// TestPersistOpState_UnknownOp tests that unknown operations return error.
func TestPersistOpState_UnknownOp(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("test-book")
	book.Store = store

	ctx := context.Background()
	if err := PersistOpState(ctx, book, OpType("nonexistent")); err == nil {
		t.Error("PersistOpState with unknown op should return error")
	}
}

// TestMemoryStateStore_CRUD tests basic create/read/update/delete operations.
func TestMemoryStateStore_CRUD(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Create
	store.SetDoc("Book", "book-1", map[string]any{
		"title":      "Test Book",
		"page_count": float64(100),
	})

	// Read via Execute
	resp, err := store.Execute(ctx, `{
		Book(filter: {_docID: {_eq: "book-1"}}) {
			title
			page_count
		}
	}`, nil)
	if err != nil {
		t.Fatalf("Execute error = %v", err)
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) != 1 {
		t.Fatalf("expected 1 book, got %v", resp.Data["Book"])
	}

	bookData := books[0].(map[string]any)
	if bookData["title"] != "Test Book" {
		t.Errorf("title = %v, want 'Test Book'", bookData["title"])
	}

	// Update via SendSync
	_, err = store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      "book-1",
		Document: map[string]any{
			"title": "Updated Title",
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		t.Fatalf("SendSync error = %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["title"] != "Updated Title" {
		t.Errorf("title after update = %v, want 'Updated Title'", doc["title"])
	}

	// Delete
	_, err = store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      "book-1",
		Op:         defra.OpDelete,
	})
	if err != nil {
		t.Fatalf("SendSync delete error = %v", err)
	}

	doc = store.GetDoc("Book", "book-1")
	if doc != nil {
		t.Error("doc should be nil after delete")
	}
}

// TestMemoryStateStore_NilValueDeletes tests that setting a field to nil removes it.
func TestMemoryStateStore_NilValueDeletes(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	store.SetDoc("Book", "book-1", map[string]any{
		"title":  "Test",
		"author": "John",
	})

	_, _ = store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      "book-1",
		Document:   map[string]any{"author": nil},
		Op:         defra.OpUpdate,
	})

	doc := store.GetDoc("Book", "book-1")
	if _, ok := doc["author"]; ok {
		t.Error("author should be deleted when set to nil")
	}
	if doc["title"] != "Test" {
		t.Error("title should still exist")
	}
}

// TestMemoryStateStore_FilterByField tests filtering by a non-_docID field.
func TestMemoryStateStore_FilterByField(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	store.SetDoc("Page", "page-1", map[string]any{"book_id": "book-1", "page_num": float64(1)})
	store.SetDoc("Page", "page-2", map[string]any{"book_id": "book-1", "page_num": float64(2)})
	store.SetDoc("Page", "page-3", map[string]any{"book_id": "book-2", "page_num": float64(1)})

	resp, err := store.Execute(ctx, `{
		Page(filter: {book_id: {_eq: "book-1"}}) {
			_docID
			page_num
		}
	}`, nil)
	if err != nil {
		t.Fatalf("Execute error = %v", err)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		t.Fatalf("expected []any, got %T", resp.Data["Page"])
	}
	if len(pages) != 2 {
		t.Errorf("expected 2 pages for book-1, got %d", len(pages))
	}
}

// TestMemoryStateStore_Reset tests clearing all data.
func TestMemoryStateStore_Reset(t *testing.T) {
	store := NewMemoryStateStore()

	store.SetDoc("Book", "book-1", map[string]any{"title": "Test"})
	store.Send(defra.WriteOp{Collection: "Book", DocID: "book-1", Op: defra.OpUpdate})

	store.Reset()

	if doc := store.GetDoc("Book", "book-1"); doc != nil {
		t.Error("doc should be nil after Reset")
	}
	if store.WriteCount() != 0 {
		t.Errorf("WriteCount should be 0 after Reset, got %d", store.WriteCount())
	}
}

// TestResetCascade_WithMemoryStore tests reset cascades using MemoryStateStore.
func TestResetCascade_WithMemoryStore(t *testing.T) {
	t.Run("toc_finder_cascades_to_extract_link_finalize_structure", func(t *testing.T) {
		book := NewBookState("test-book")
		store := NewMemoryStateStore()
		book.Store = store
		book.SetTocDocID("toc-1")

		// Start and complete all downstream operations
		for _, op := range []OpType{OpTocFinder, OpTocExtract, OpTocLink, OpTocFinalize, OpStructure} {
			_ = book.OpStart(op)
			book.OpComplete(op)
		}

		// Verify all are complete
		for _, op := range []OpType{OpTocFinder, OpTocExtract, OpTocLink, OpTocFinalize, OpStructure} {
			if !book.OpIsComplete(op) {
				t.Fatalf("expected %s to be complete before reset", op)
			}
		}

		// Reset toc_finder - should cascade
		ctx := context.Background()
		if err := ResetFrom(ctx, book, "toc-1", ResetTocFinder); err != nil {
			t.Fatalf("ResetFrom error = %v", err)
		}

		// TocFinder and all downstream should be reset
		for _, op := range []OpType{OpTocFinder, OpTocExtract, OpTocLink, OpTocFinalize, OpStructure} {
			if !book.OpCanStart(op) {
				t.Errorf("expected %s to be reset (CanStart=true) after cascade", op)
			}
		}
	})

	t.Run("metadata_no_cascade", func(t *testing.T) {
		book := NewBookState("test-book")
		store := NewMemoryStateStore()
		book.Store = store

		_ = book.OpStart(OpMetadata)
		book.OpComplete(OpMetadata)
		_ = book.OpStart(OpTocFinder)
		book.OpComplete(OpTocFinder)

		ctx := context.Background()
		if err := ResetFrom(ctx, book, "", ResetMetadata); err != nil {
			t.Fatalf("ResetFrom error = %v", err)
		}

		if !book.OpCanStart(OpMetadata) {
			t.Error("metadata should be reset")
		}
		if !book.OpIsComplete(OpTocFinder) {
			t.Error("toc_finder should NOT be affected by metadata reset")
		}
	})

	t.Run("pattern_analysis_cascades_to_toc_link", func(t *testing.T) {
		book := NewBookState("test-book")
		store := NewMemoryStateStore()
		book.Store = store
		book.SetTocDocID("toc-1")

		// Complete pattern analysis and downstream
		_ = book.OpStart(OpPatternAnalysis)
		book.OpComplete(OpPatternAnalysis)
		_ = book.OpStart(OpTocLink)
		book.OpComplete(OpTocLink)
		_ = book.OpStart(OpTocFinalize)
		book.OpComplete(OpTocFinalize)

		ctx := context.Background()
		if err := ResetFrom(ctx, book, "toc-1", ResetPatternAnalysis); err != nil {
			t.Fatalf("ResetFrom error = %v", err)
		}

		if !book.OpCanStart(OpPatternAnalysis) {
			t.Error("pattern_analysis should be reset")
		}
		if !book.OpCanStart(OpTocLink) {
			t.Error("toc_link should be reset via cascade")
		}
		if !book.OpCanStart(OpTocFinalize) {
			t.Error("toc_finalize should be reset via cascade from toc_link")
		}
	})

	t.Run("structure_no_cascade", func(t *testing.T) {
		book := NewBookState("test-book")
		store := NewMemoryStateStore()
		book.Store = store

		_ = book.OpStart(OpStructure)
		book.OpComplete(OpStructure)

		ctx := context.Background()
		if err := ResetFrom(ctx, book, "", ResetStructure); err != nil {
			t.Fatalf("ResetFrom error = %v", err)
		}

		if !book.OpCanStart(OpStructure) {
			t.Error("structure should be reset")
		}
	})
}

// TestResetFrom_InvalidOperation tests that invalid operations return error.
func TestResetFrom_InvalidOperation(t *testing.T) {
	book := NewBookState("test-book")
	store := NewMemoryStateStore()
	book.Store = store

	ctx := context.Background()
	err := ResetFrom(ctx, book, "", ResetOperation("nonexistent"))
	if err == nil {
		t.Error("ResetFrom with invalid operation should return error")
	}
}

// TestPersistAndReload_Roundtrip tests that persist + load produces the same state.
func TestPersistAndReload_Roundtrip(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Create first book with state
	book1 := NewBookState("test-book")
	book1.Store = store
	book1.SetTocDocID("toc-1")

	_ = book1.OpStart(OpMetadata)
	book1.OpComplete(OpMetadata)
	_ = book1.OpStart(OpTocFinder)
	// Leave toc_finder as started (not complete)

	// Persist both ops
	if err := PersistOpState(ctx, book1, OpMetadata); err != nil {
		t.Fatalf("persist metadata error = %v", err)
	}
	if err := PersistOpState(ctx, book1, OpTocFinder); err != nil {
		t.Fatalf("persist toc_finder error = %v", err)
	}

	// Create a new book and load state from what was persisted
	book2 := NewBookState("test-book")
	book2.Store = store

	// Manually load from the store's writes (simulating what LoadBookOperationState does)
	metadataDoc := store.GetDoc("Book", "test-book")
	if metadataDoc != nil {
		loadOpStateFromData(book2, OpMetadata, metadataDoc, "metadata")
	}

	tocDoc := store.GetDoc("ToC", "toc-1")
	if tocDoc != nil {
		loadOpStateFromData(book2, OpTocFinder, tocDoc, "finder")
	}

	// Verify states match
	if !book2.OpIsComplete(OpMetadata) {
		t.Error("metadata should be complete after reload")
	}
	if !book2.OpIsStarted(OpTocFinder) {
		t.Error("toc_finder should be started after reload")
	}
	if book2.OpIsComplete(OpTocFinder) {
		t.Error("toc_finder should not be complete after reload")
	}
}

// TestDocIDSource_Book verifies that Book operations use BookDocID.
func TestDocIDSource_Book(t *testing.T) {
	book := NewBookState("book-123")

	for _, op := range []OpType{OpMetadata, OpPatternAnalysis, OpStructure} {
		cfg := OpRegistry[op]
		docID := cfg.DocIDSource(book)
		if docID != "book-123" {
			t.Errorf("DocIDSource(%s) = %s, want book-123", op, docID)
		}
	}
}

// TestDocIDSource_ToC verifies that ToC operations use TocDocID.
func TestDocIDSource_ToC(t *testing.T) {
	book := NewBookState("book-123")
	book.SetTocDocID("toc-456")

	for _, op := range []OpType{OpTocFinder, OpTocExtract, OpTocLink, OpTocFinalize} {
		cfg := OpRegistry[op]
		docID := cfg.DocIDSource(book)
		if docID != "toc-456" {
			t.Errorf("DocIDSource(%s) = %s, want toc-456", op, docID)
		}
	}
}

// TestDocIDSource_EmptyToC verifies that ToC operations return empty when no TocDocID.
func TestDocIDSource_EmptyToC(t *testing.T) {
	book := NewBookState("book-123")
	// Don't set TocDocID

	for _, op := range []OpType{OpTocFinder, OpTocExtract, OpTocLink, OpTocFinalize} {
		cfg := OpRegistry[op]
		docID := cfg.DocIDSource(book)
		if docID != "" {
			t.Errorf("DocIDSource(%s) = %s, want empty when no TocDocID", op, docID)
		}
	}
}
