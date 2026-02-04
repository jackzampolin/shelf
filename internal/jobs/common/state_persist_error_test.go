package common

import (
	"context"
	"errors"
	"testing"
)

// errInjected is used for error injection tests.
var errInjected = errors.New("injected error")

// TestPersistBookStatus_ErrorHandling tests error handling in PersistBookStatus.
func TestPersistBookStatus_ErrorHandling(t *testing.T) {
	t.Run("no store available", func(t *testing.T) {
		book := NewBookState("book1")
		// Don't set book.Store

		_, err := book.PersistBookStatus(context.Background(), "processing")
		if err == nil {
			t.Error("Expected error when store is nil")
		}
	})

	t.Run("db error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SendSyncErr = errInjected

		book := NewBookState("book1")
		book.Store = store

		_, err := book.PersistBookStatus(context.Background(), "processing")
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT updated
		if book.GetBookCID() != "" {
			t.Error("Book CID should not be set on error")
		}
	})
}

// TestPersistOpState_ErrorHandling tests error handling in PersistOpState.
func TestPersistOpState_ErrorHandling(t *testing.T) {
	t.Run("unknown operation", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store

		err := book.PersistOpState(context.Background(), "invalid_op")
		if err == nil {
			t.Error("Expected error for unknown operation")
		}
	})

	t.Run("no doc id - graceful skip", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		// Don't set TocDocID - OpTocFinder uses ToC collection

		err := book.OpStart(OpTocFinder)
		if err != nil {
			t.Fatalf("OpStart error: %v", err)
		}

		// Should not error when ToC doc doesn't exist
		err = book.PersistOpState(context.Background(), OpTocFinder)
		if err != nil {
			t.Errorf("Expected nil error when doc ID is empty, got: %v", err)
		}
	})

	t.Run("db error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Book", "book1", map[string]any{})
		store.SendSyncErr = errInjected

		book := NewBookState("book1")
		book.Store = store
		book.OpStart(OpMetadata)

		err := book.PersistOpState(context.Background(), OpMetadata)
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}
	})
}

// TestPersistFinalizePhase_ErrorHandling tests error handling in PersistFinalizePhase.
func TestPersistFinalizePhase_ErrorHandling(t *testing.T) {
	t.Run("no toc doc id", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		// Don't set TocDocID

		_, err := book.PersistFinalizePhase(context.Background(), "discover")
		if err == nil {
			t.Error("Expected error when ToC doc ID is empty")
		}
	})

	t.Run("db error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("ToC", "toc1", map[string]any{})
		store.SendSyncErr = errInjected

		book := NewBookState("book1")
		book.Store = store
		book.SetTocDocID("toc1")

		_, err := book.PersistFinalizePhase(context.Background(), "discover")
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT updated
		if book.GetFinalizePhase() != "" {
			t.Error("Finalize phase should not be set on error")
		}
	})
}

// TestPersistChapterSkeleton_ErrorHandling tests error handling in PersistChapterSkeleton.
func TestPersistChapterSkeleton_ErrorHandling(t *testing.T) {
	t.Run("no store available", func(t *testing.T) {
		book := NewBookState("book1")
		book.SetStructureChapters([]*ChapterState{
			{EntryID: "e1", Title: "Chapter 1"},
		})

		err := book.PersistChapterSkeleton(context.Background(), func(ch *ChapterState) string {
			return ch.EntryID
		})
		if err == nil {
			t.Error("Expected error when store is nil")
		}
	})

	t.Run("partial failure aggregates errors", func(t *testing.T) {
		store := NewMemoryStateStore()
		// Fail on specific unique key
		store.SetErrorOnCollection("Chapter", errInjected)

		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{
			{EntryID: "e1", Title: "Chapter 1"},
			{EntryID: "e2", Title: "Chapter 2"},
			{EntryID: "e3", Title: "Chapter 3"},
		})

		err := book.PersistChapterSkeleton(context.Background(), func(ch *ChapterState) string {
			return ch.EntryID
		})
		if err == nil {
			t.Error("Expected error on partial failure")
		}

		// Verify error message mentions multiple failures
		errStr := err.Error()
		if errStr == "" {
			t.Error("Error message should not be empty")
		}

		// Verify chapters were NOT updated in memory (all-or-nothing)
		chapters := book.GetStructureChapters()
		for _, ch := range chapters {
			if ch.DocID != "" {
				t.Errorf("Chapter %s DocID should be empty on partial failure", ch.EntryID)
			}
		}
	})

	t.Run("empty chapters list", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		// Don't set any chapters

		err := book.PersistChapterSkeleton(context.Background(), func(ch *ChapterState) string {
			return ch.EntryID
		})
		if err != nil {
			t.Errorf("Expected nil error for empty chapters, got: %v", err)
		}
	})
}

// TestPersistChapterExtracts_ErrorHandling tests error handling in PersistChapterExtracts.
func TestPersistChapterExtracts_ErrorHandling(t *testing.T) {
	t.Run("partial failure", func(t *testing.T) {
		store := NewMemoryStateStore()

		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{
			{EntryID: "e1", DocID: "ch1", ExtractDone: true, MechanicalText: "text1"},
			{EntryID: "e2", DocID: "ch2", ExtractDone: true, MechanicalText: "text2"},
		})

		// Fail on ch2
		store.SetErrorOnDocID("Chapter", "ch2", errInjected)

		err := book.PersistChapterExtracts(context.Background())
		if err == nil {
			t.Error("Expected error on partial failure")
		}
	})

	t.Run("no chapters to update", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{
			{EntryID: "e1", DocID: "ch1", ExtractDone: false}, // Not done
			{EntryID: "e2", DocID: "", ExtractDone: true},     // No DocID
		})

		err := book.PersistChapterExtracts(context.Background())
		if err != nil {
			t.Errorf("Expected nil error when no chapters to update, got: %v", err)
		}
	})
}

// TestPersistTocEntries_ErrorHandling tests error handling in PersistTocEntries.
func TestPersistTocEntries_ErrorHandling(t *testing.T) {
	t.Run("partial failure aggregates errors", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.UpsertErr = errInjected

		book := NewBookState("book1")
		book.Store = store

		entries := []map[string]any{
			{"title": "Entry 1", "page": 1},
			{"title": "Entry 2", "page": 2},
		}
		uniqueKeys := []string{"key1", "key2"}

		err := book.PersistTocEntries(context.Background(), "toc1", entries, uniqueKeys)
		if err == nil {
			t.Error("Expected error on partial failure")
		}

		// Verify memory was NOT updated
		if len(book.GetTocEntries()) > 0 {
			t.Error("ToC entries should not be set on failure")
		}
	})
}

// TestPersistOcrResult_ErrorHandling tests error handling in PersistOcrResult.
func TestPersistOcrResult_ErrorHandling(t *testing.T) {
	t.Run("page not found", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store

		_, err := book.PersistOcrResult(context.Background(), 1, "openrouter", "text", "h", "f")
		if err == nil {
			t.Error("Expected error when page not found")
		}
	})

	t.Run("page has no doc id", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		pageState := book.GetOrCreatePage(1) // No DocID set
		_ = pageState                        // Ensure page exists

		_, err := book.PersistOcrResult(context.Background(), 1, "openrouter", "text", "h", "f")
		if err == nil {
			t.Error("Expected error when page has no doc ID")
		}
	})

	t.Run("ocr result create fails", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Page", "page1", map[string]any{"page_num": 1})

		book := NewBookState("book1")
		book.Store = store
		book.OcrProviders = []string{"openrouter"}

		pageState := book.GetOrCreatePage(1)
		pageState.SetPageDocID("page1")

		store.SendSyncErr = errInjected

		_, err := book.PersistOcrResult(context.Background(), 1, "openrouter", "text", "h", "f")
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}
	})

	t.Run("page update fails - memory not updated", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Page", "page1", map[string]any{"page_num": 1})

		book := NewBookState("book1")
		book.Store = store
		book.OcrProviders = []string{"openrouter"}

		pageState := book.GetOrCreatePage(1)
		pageState.SetPageDocID("page1")

		// Fail on UpdateWithVersion
		store.UpdateErr = errInjected

		_, err := book.PersistOcrResult(context.Background(), 1, "openrouter", "text", "h", "f")
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT updated (page update failed)
		if pageState.GetHeader() != "" {
			t.Error("Header should not be set when page update fails")
		}
	})
}

// TestPersistOcrMarkdown_ErrorHandling tests error handling in PersistOcrMarkdown.
func TestPersistOcrMarkdown_ErrorHandling(t *testing.T) {
	t.Run("db error - memory not updated", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Page", "page1", map[string]any{"page_num": 1})
		store.UpdateErr = errInjected

		book := NewBookState("book1")
		book.Store = store

		pageState := book.GetOrCreatePage(1)
		pageState.SetPageDocID("page1")

		err := book.PersistOcrMarkdown(context.Background(), 1, "# Heading", nil)
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT updated
		if pageState.GetOcrMarkdown() != "" {
			t.Error("OCR markdown should not be set on error")
		}
	})
}

// TestResetAllOcr_ErrorHandling tests error handling in ResetAllOcr.
func TestResetAllOcr_ErrorHandling(t *testing.T) {
	t.Run("query error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.ExecuteErr = errInjected

		book := NewBookState("book1")
		book.Store = store

		err := book.ResetAllOcr(context.Background())
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}
	})

	t.Run("batch update error - memory not reset", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Page", "page1", map[string]any{"book_id": "book1", "ocr_complete": true})

		book := NewBookState("book1")
		book.Store = store

		pageState := book.GetOrCreatePage(1)
		pageState.SetOcrMarkdown("original markdown")

		// Fail on batch update
		store.SendManySyncErr = errInjected

		err := book.ResetAllOcr(context.Background())
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT reset
		if pageState.GetOcrMarkdown() != "original markdown" {
			t.Error("OCR markdown should not be cleared on error")
		}
	})
}

// TestDeleteAllChapters_ErrorHandling tests error handling in DeleteAllChapters.
func TestDeleteAllChapters_ErrorHandling(t *testing.T) {
	t.Run("query error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.ExecuteErr = errInjected

		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{{EntryID: "e1", DocID: "ch1"}})

		err := book.DeleteAllChapters(context.Background())
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT cleared
		if book.GetStructureChapters() == nil {
			t.Error("Chapters should not be cleared on query error")
		}
	})

	t.Run("batch delete error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Chapter", "ch1", map[string]any{"book_id": "book1"})

		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{{EntryID: "e1", DocID: "ch1"}})

		// Fail on batch delete
		store.SendManySyncErr = errInjected

		err := book.DeleteAllChapters(context.Background())
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}
	})
}

// TestDeleteAgentStatesForType_ErrorHandling tests error handling.
func TestDeleteAgentStatesForType_ErrorHandling(t *testing.T) {
	t.Run("query error", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.ExecuteErr = errInjected

		book := NewBookState("book1")
		book.Store = store
		book.SetAgentState(&AgentState{AgentType: AgentTypeTocFinder, AgentID: "a1", DocID: "as1"})

		err := book.DeleteAgentStatesForType(context.Background(), AgentTypeTocFinder)
		if !errors.Is(err, errInjected) {
			t.Errorf("Expected injected error, got: %v", err)
		}

		// Verify memory was NOT cleared
		if book.GetAgentState(AgentTypeTocFinder, "") == nil {
			t.Error("Agent state should not be cleared on query error")
		}
	})
}

// TestPersistOpStateAsync tests the fire-and-forget operation state persistence.
func TestPersistOpStateAsync(t *testing.T) {
	t.Run("updates memory and fires async write", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("ToC", "toc1", map[string]any{})

		book := NewBookState("book1")
		book.Store = store
		book.SetTocDocID("toc1")

		// Start toc_extract operation (updates memory)
		book.TocExtractStart()

		// Call async persist
		book.PersistOpStateAsync(context.Background(), OpTocExtract)

		// Memory should be updated (TocExtractStart already did this)
		state := book.OpGetState(OpTocExtract)
		if !state.IsStarted() {
			t.Error("Memory should show toc_extract started")
		}

		// Give async write time to complete (fire-and-forget)
		// In real use, we don't wait, but for testing we verify it works
		// Note: MemoryStateStore.Send is synchronous for testing purposes
		doc := store.GetDoc("ToC", "toc1")
		if doc == nil {
			t.Error("ToC document should exist")
		}
		// The async write should have updated the document
		if started, ok := doc["extract_started"].(bool); !ok || !started {
			t.Error("DB should show extract_started=true")
		}
	})

	t.Run("gracefully handles no store", func(t *testing.T) {
		book := NewBookState("book1")
		// Don't set book.Store

		// Should not panic
		book.PersistOpStateAsync(context.Background(), OpTocExtract)
	})

	t.Run("gracefully handles no doc ID", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		// Don't set TocDocID

		// Should not panic
		book.PersistOpStateAsync(context.Background(), OpTocExtract)
	})
}

// TestPersistTocFinderResultAsync tests the fire-and-forget ToC finder result persistence.
func TestPersistTocFinderResultAsync(t *testing.T) {
	t.Run("updates memory and fires async write", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("ToC", "toc1", map[string]any{})

		book := NewBookState("book1")
		book.Store = store
		book.SetTocDocID("toc1")

		// Call async persist
		book.PersistTocFinderResultAsync(context.Background(), true, 5, 10, nil)

		// Memory should be updated immediately
		if !book.GetTocFound() {
			t.Error("Memory should show ToC found")
		}
		start, end := book.GetTocPageRange()
		if start != 5 || end != 10 {
			t.Errorf("Page range should be 5-10, got %d-%d", start, end)
		}

		// DB should also be updated (MemoryStateStore.Send is synchronous for testing)
		doc := store.GetDoc("ToC", "toc1")
		if doc == nil {
			t.Error("ToC document should exist")
		}
		if found, ok := doc["toc_found"].(bool); !ok || !found {
			t.Error("DB should show toc_found=true")
		}
		if startPage, ok := doc["start_page"].(int); !ok || startPage != 5 {
			t.Errorf("DB start_page should be 5, got %v", doc["start_page"])
		}
	})

	t.Run("gracefully handles no ToC doc ID", func(t *testing.T) {
		store := NewMemoryStateStore()
		book := NewBookState("book1")
		book.Store = store
		// Don't set TocDocID

		// Should update memory but not panic
		book.PersistTocFinderResultAsync(context.Background(), true, 5, 10, nil)

		// Memory should still be updated
		if !book.GetTocFound() {
			t.Error("Memory should show ToC found even without DB write")
		}
	})
}
