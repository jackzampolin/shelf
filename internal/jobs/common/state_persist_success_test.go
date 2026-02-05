package common

import (
	"context"
	"testing"
)

// TestPersistChapterSkeleton_Success tests successful chapter skeleton persistence.
func TestPersistChapterSkeleton_Success(t *testing.T) {
	t.Run("creates new chapters", func(t *testing.T) {
		store := NewMemoryStateStore()

		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{
			{EntryID: "e1", Title: "Chapter 1", Level: 1, SortOrder: 1, StartPage: 1, EndPage: 10},
			{EntryID: "e2", Title: "Chapter 2", Level: 1, SortOrder: 2, StartPage: 11, EndPage: 20},
		})

		err := book.PersistChapterSkeleton(context.Background(), func(ch *ChapterState) string {
			return "book1:" + ch.EntryID
		})
		if err != nil {
			t.Fatalf("PersistChapterSkeleton error: %v", err)
		}

		// Verify chapters have DocID and CID set
		chapters := book.GetStructureChapters()
		for _, ch := range chapters {
			if ch.DocID == "" {
				t.Errorf("Chapter %s DocID should be set", ch.EntryID)
			}
			if ch.CID == "" {
				t.Errorf("Chapter %s CID should be set", ch.EntryID)
			}
			if ch.UniqueKey == "" {
				t.Errorf("Chapter %s UniqueKey should be set", ch.EntryID)
			}
		}

		// Verify docs exist in store
		writes := store.GetWrites()
		if len(writes) != 2 {
			t.Errorf("Expected 2 writes, got %d", len(writes))
		}
	})

	t.Run("updates existing chapters", func(t *testing.T) {
		store := NewMemoryStateStore()
		// Pre-create a chapter
		store.SetDoc("Chapter", "existing-ch1", map[string]any{
			"unique_key": "book1:e1",
			"title":      "Old Title",
		})

		book := NewBookState("book1")
		book.Store = store
		book.SetStructureChapters([]*ChapterState{
			{EntryID: "e1", Title: "New Title", Level: 1},
		})

		err := book.PersistChapterSkeleton(context.Background(), func(ch *ChapterState) string {
			return "book1:" + ch.EntryID
		})
		if err != nil {
			t.Fatalf("PersistChapterSkeleton error: %v", err)
		}

		// Verify the chapter was updated
		chapters := book.GetStructureChapters()
		if chapters[0].DocID != "existing-ch1" {
			t.Errorf("Expected existing DocID, got: %s", chapters[0].DocID)
		}

		// Verify title was updated in store
		doc := store.GetDoc("Chapter", "existing-ch1")
		if doc["title"] != "New Title" {
			t.Errorf("Title should be updated, got: %v", doc["title"])
		}
	})
}

// TestPersistChapterExtracts_Success tests successful extract persistence.
func TestPersistChapterExtracts_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Chapter", "ch1", map[string]any{"title": "Chapter 1"})
	store.SetDoc("Chapter", "ch2", map[string]any{"title": "Chapter 2"})

	book := NewBookState("book1")
	book.Store = store
	book.SetStructureChapters([]*ChapterState{
		{EntryID: "e1", DocID: "ch1", ExtractDone: true, MechanicalText: "Extracted text 1"},
		{EntryID: "e2", DocID: "ch2", ExtractDone: true, MechanicalText: "Extracted text 2"},
		{EntryID: "e3", DocID: "ch3", ExtractDone: false}, // Not done, should be skipped
	})

	err := book.PersistChapterExtracts(context.Background())
	if err != nil {
		t.Fatalf("PersistChapterExtracts error: %v", err)
	}

	// Verify CIDs were updated
	chapters := book.GetStructureChapters()
	for i, ch := range chapters {
		if i < 2 && ch.CID == "" {
			t.Errorf("Chapter %s CID should be set", ch.EntryID)
		}
	}

	// Verify DB was updated
	doc1 := store.GetDoc("Chapter", "ch1")
	if doc1["mechanical_text"] != "Extracted text 1" {
		t.Errorf("Chapter 1 mechanical_text = %v", doc1["mechanical_text"])
	}
}

// TestPersistChapterClassifications_Success tests successful classification persistence.
func TestPersistChapterClassifications_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Chapter", "ch1", map[string]any{"title": "Chapter 1"})

	book := NewBookState("book1")
	book.Store = store
	book.SetStructureChapters([]*ChapterState{
		{
			EntryID:          "e1",
			DocID:            "ch1",
			MatterType:       "body",
			ContentType:      "prose",
			AudioInclude:     true,
			ClassifyReasoning: "This is main content",
		},
	})

	err := book.PersistChapterClassifications(context.Background())
	if err != nil {
		t.Fatalf("PersistChapterClassifications error: %v", err)
	}

	// Verify DB was updated
	doc := store.GetDoc("Chapter", "ch1")
	if doc["matter_type"] != "body" {
		t.Errorf("matter_type = %v, want 'body'", doc["matter_type"])
	}
	if doc["content_type"] != "prose" {
		t.Errorf("content_type = %v, want 'prose'", doc["content_type"])
	}
	if doc["audio_include"] != true {
		t.Errorf("audio_include = %v, want true", doc["audio_include"])
	}
}

// TestPersistChapterPolish_Success tests successful polish persistence.
func TestPersistChapterPolish_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Chapter", "ch1", map[string]any{"title": "Chapter 1"})

	book := NewBookState("book1")
	book.Store = store
	book.SetStructureChapters([]*ChapterState{
		{
			EntryID:      "e1",
			DocID:        "ch1",
			PolishDone:   true,
			PolishedText: "Polished content here",
			WordCount:    100,
		},
	})

	err := book.PersistChapterPolish(context.Background())
	if err != nil {
		t.Fatalf("PersistChapterPolish error: %v", err)
	}

	// Verify DB was updated
	doc := store.GetDoc("Chapter", "ch1")
	if doc["polished_text"] != "Polished content here" {
		t.Errorf("polished_text = %v", doc["polished_text"])
	}
	if doc["word_count"] != 100 {
		t.Errorf("word_count = %v, want 100", doc["word_count"])
	}
}

// TestPersistTocEntries_Success tests successful ToC entries persistence.
func TestPersistTocEntries_Success(t *testing.T) {
	t.Run("creates new entries", func(t *testing.T) {
		store := NewMemoryStateStore()

		book := NewBookState("book1")
		book.Store = store

		entries := []map[string]any{
			{"title": "Chapter 1", "page": 1, "level": 1},
			{"title": "Chapter 2", "page": 15, "level": 1},
		}
		uniqueKeys := []string{"toc1:ch1", "toc1:ch2"}

		err := book.PersistTocEntries(context.Background(), "toc1", entries, uniqueKeys)
		if err != nil {
			t.Fatalf("PersistTocEntries error: %v", err)
		}

		// Verify writes happened
		if store.WriteCount() != 2 {
			t.Errorf("Expected 2 writes, got %d", store.WriteCount())
		}
	})

	t.Run("updates existing entries", func(t *testing.T) {
		store := NewMemoryStateStore()
		// Pre-create an entry
		store.SetDoc("TocEntry", "existing-te1", map[string]any{
			"unique_key": "toc1:ch1",
			"title":      "Old Title",
		})

		book := NewBookState("book1")
		book.Store = store

		entries := []map[string]any{
			{"title": "New Title", "page": 1},
		}
		uniqueKeys := []string{"toc1:ch1"}

		err := book.PersistTocEntries(context.Background(), "toc1", entries, uniqueKeys)
		if err != nil {
			t.Fatalf("PersistTocEntries error: %v", err)
		}

		// Verify the entry was updated
		doc := store.GetDoc("TocEntry", "existing-te1")
		if doc["title"] != "New Title" {
			t.Errorf("Title should be updated, got: %v", doc["title"])
		}
	})
}

// TestPersistTocEntryLink_Success tests successful ToC entry linking.
func TestPersistTocEntryLink_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("TocEntry", "te1", map[string]any{"title": "Chapter 1"})

	book := NewBookState("book1")
	book.Store = store

	// Set up the entry in linkedEntries first (required by PersistTocEntryLink)
	book.SetLinkedEntries([]*LinkedTocEntry{
		{DocID: "te1", Title: "Chapter 1"},
	})

	cid, err := book.PersistTocEntryLink(context.Background(), "te1", "page1", 5)
	if err != nil {
		t.Fatalf("PersistTocEntryLink error: %v", err)
	}
	if cid == "" {
		t.Error("CID should not be empty")
	}

	// Verify DB was updated (only actual_page_id is stored, not actual_page)
	doc := store.GetDoc("TocEntry", "te1")
	if doc["actual_page_id"] != "page1" {
		t.Errorf("actual_page_id = %v, want 'page1'", doc["actual_page_id"])
	}

	// Verify entry was updated in linkedEntries
	linkedEntries := book.GetLinkedEntries()
	if len(linkedEntries) != 1 {
		t.Errorf("Expected 1 linked entry, got %d", len(linkedEntries))
	}
	if linkedEntries[0].ActualPage == nil || *linkedEntries[0].ActualPage != 5 {
		t.Error("LinkedEntry ActualPage should be 5")
	}
	if linkedEntries[0].ActualPageDocID != "page1" {
		t.Errorf("LinkedEntry ActualPageDocID = %v, want 'page1'", linkedEntries[0].ActualPageDocID)
	}
}

// TestPersistOcrResult_Success tests successful OCR result persistence.
func TestPersistOcrResult_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Page", "page1", map[string]any{"page_num": 1, "book_id": "book1"})

	book := NewBookState("book1")
	book.Store = store
	book.OcrProviders = []string{"openrouter", "mistral"}

	pageState := book.GetOrCreatePage(1)
	pageState.SetPageDocID("page1")

	// First provider
	allDone, err := book.PersistOcrResult(context.Background(), 1, "openrouter", "OCR text", "Header", "Footer")
	if err != nil {
		t.Fatalf("PersistOcrResult error: %v", err)
	}
	if allDone {
		t.Error("Should not be all done after first provider")
	}

	// Verify memory was updated
	if pageState.GetHeader() != "Header" {
		t.Errorf("Header = %v, want 'Header'", pageState.GetHeader())
	}
	if pageState.GetFooter() != "Footer" {
		t.Errorf("Footer = %v, want 'Footer'", pageState.GetFooter())
	}

	// Second provider
	allDone, err = book.PersistOcrResult(context.Background(), 1, "mistral", "OCR text 2", "Header", "Footer")
	if err != nil {
		t.Fatalf("PersistOcrResult error: %v", err)
	}
	if !allDone {
		t.Error("Should be all done after all providers")
	}

	// Verify DB has ocr_complete=true
	doc := store.GetDoc("Page", "page1")
	if doc["ocr_complete"] != true {
		t.Errorf("ocr_complete = %v, want true", doc["ocr_complete"])
	}
}

// TestPersistOcrMarkdown_Success tests successful OCR markdown persistence.
func TestPersistOcrMarkdown_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Page", "page1", map[string]any{"page_num": 1})

	book := NewBookState("book1")
	book.Store = store

	pageState := book.GetOrCreatePage(1)
	pageState.SetPageDocID("page1")

	markdown := "# Heading\n\nParagraph text here."
	headings := map[string]any{"headings": `[{"level":1,"text":"Heading"}]`}

	err := book.PersistOcrMarkdown(context.Background(), 1, markdown, headings)
	if err != nil {
		t.Fatalf("PersistOcrMarkdown error: %v", err)
	}

	// Verify memory was updated
	if pageState.GetOcrMarkdown() != markdown {
		t.Errorf("OCR markdown = %v, want %v", pageState.GetOcrMarkdown(), markdown)
	}

	// Verify DB was updated
	doc := store.GetDoc("Page", "page1")
	if doc["ocr_markdown"] != markdown {
		t.Errorf("DB ocr_markdown = %v", doc["ocr_markdown"])
	}
	if doc["headings"] != `[{"level":1,"text":"Heading"}]` {
		t.Errorf("DB headings = %v", doc["headings"])
	}
}

// TestResetAllOcr_Success tests successful OCR reset.
func TestResetAllOcr_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Page", "page1", map[string]any{"book_id": "book1", "ocr_complete": true, "ocr_markdown": "old"})
	store.SetDoc("Page", "page2", map[string]any{"book_id": "book1", "ocr_complete": true, "ocr_markdown": "old"})
	store.SetDoc("Page", "page3", map[string]any{"book_id": "book1", "ocr_complete": false}) // Not complete

	book := NewBookState("book1")
	book.Store = store

	pageState1 := book.GetOrCreatePage(1)
	pageState1.SetOcrMarkdown("old markdown 1")

	pageState2 := book.GetOrCreatePage(2)
	pageState2.SetOcrMarkdown("old markdown 2")

	err := book.ResetAllOcr(context.Background())
	if err != nil {
		t.Fatalf("ResetAllOcr error: %v", err)
	}

	// Verify memory was cleared
	if pageState1.GetOcrMarkdown() != "" {
		t.Error("Page 1 OCR markdown should be cleared")
	}
	if pageState2.GetOcrMarkdown() != "" {
		t.Error("Page 2 OCR markdown should be cleared")
	}

	// Verify DB was updated
	doc1 := store.GetDoc("Page", "page1")
	if doc1["ocr_complete"] != false {
		t.Errorf("page1 ocr_complete = %v, want false", doc1["ocr_complete"])
	}
}

// TestPersistNewAgentStates_Success tests batch agent state creation.
func TestPersistNewAgentStates_Success(t *testing.T) {
	store := NewMemoryStateStore()
	book := NewBookState("book1")
	book.Store = store

	states := []*AgentState{
		{AgentID: "agent1", AgentType: AgentTypeTocFinder, Iteration: 1},
		{AgentID: "agent2", AgentType: AgentTypeChapterFinder, Iteration: 1, EntryDocID: "entry1"},
	}

	err := book.PersistNewAgentStates(context.Background(), states)
	if err != nil {
		t.Fatalf("PersistNewAgentStates error: %v", err)
	}

	// Verify DocIDs were set
	for i, state := range states {
		if state.DocID == "" {
			t.Errorf("State %d DocID should be set", i)
		}
		if state.CID == "" {
			t.Errorf("State %d CID should be set", i)
		}
	}

	// Verify agents are in memory
	if book.GetAgentState(AgentTypeTocFinder, "") == nil {
		t.Error("TocFinder agent should be in memory")
	}
	if book.GetAgentState(AgentTypeChapterFinder, "entry1") == nil {
		t.Error("ChapterFinder agent should be in memory")
	}
}

// TestDeleteAllAgentStates_Success tests deleting all agent states.
func TestDeleteAllAgentStates_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("AgentState", "as1", map[string]any{"book_id": "book1", "agent_type": "toc_finder"})
	store.SetDoc("AgentState", "as2", map[string]any{"book_id": "book1", "agent_type": "chapter_finder"})
	store.SetDoc("AgentState", "as3", map[string]any{"book_id": "book2", "agent_type": "toc_finder"}) // Other book

	book := NewBookState("book1")
	book.Store = store
	book.SetAgentState(&AgentState{AgentType: AgentTypeTocFinder, AgentID: "a1", DocID: "as1"})
	book.SetAgentState(&AgentState{AgentType: AgentTypeChapterFinder, AgentID: "a2", DocID: "as2"})

	err := book.DeleteAllAgentStates(context.Background())
	if err != nil {
		t.Fatalf("DeleteAllAgentStates error: %v", err)
	}

	// Verify book1 states were deleted
	if store.GetDoc("AgentState", "as1") != nil {
		t.Error("as1 should be deleted")
	}
	if store.GetDoc("AgentState", "as2") != nil {
		t.Error("as2 should be deleted")
	}

	// Verify book2 state is still there
	if store.GetDoc("AgentState", "as3") == nil {
		t.Error("as3 should not be deleted")
	}

	// Verify memory was cleared
	if book.GetAgentState(AgentTypeTocFinder, "") != nil {
		t.Error("TocFinder agent should be cleared")
	}
	if book.GetAgentState(AgentTypeChapterFinder, "") != nil {
		t.Error("ChapterFinder agent should be cleared")
	}
}

// TestPersistMetadataResult_Success tests metadata persistence.
func TestPersistMetadataResult_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book1", map[string]any{"title": "Original"})

	book := NewBookState("book1")
	book.Store = store

	metadata := &BookMetadata{
		Title:       "New Title",
		Author:      "Author Name",
		Description: "Description",
	}
	fields := map[string]any{
		"title":       "New Title",
		"author":      "Author Name",
		"description": "Description",
	}

	cid, err := book.PersistMetadataResult(context.Background(), metadata, fields)
	if err != nil {
		t.Fatalf("PersistMetadataResult error: %v", err)
	}
	if cid == "" {
		t.Error("CID should not be empty")
	}

	// Verify DB was updated
	doc := store.GetDoc("Book", "book1")
	if doc["title"] != "New Title" {
		t.Errorf("title = %v, want 'New Title'", doc["title"])
	}

	// Verify memory was updated
	retrieved := book.GetBookMetadata()
	if retrieved == nil || retrieved.Title != "New Title" {
		t.Error("Metadata should be updated in memory")
	}
}

// TestPersistFinalizeProgress_Success tests finalize progress persistence.
func TestPersistFinalizeProgress_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book1", map[string]any{})

	book := NewBookState("book1")
	book.Store = store
	book.SetFinalizeEntriesTotal(10)
	book.SetFinalizeGapsTotal(3)
	book.SetFinalizeProgress(5, 3, 2, 1)

	err := book.PersistFinalizeProgress(context.Background())
	if err != nil {
		t.Fatalf("PersistFinalizeProgress error: %v", err)
	}

	// Verify DB was updated
	doc := store.GetDoc("Book", "book1")
	if doc["finalize_entries_total"] != 10 {
		t.Errorf("finalize_entries_total = %v, want 10", doc["finalize_entries_total"])
	}
	if doc["finalize_entries_complete"] != 5 {
		t.Errorf("finalize_entries_complete = %v, want 5", doc["finalize_entries_complete"])
	}
}

// TestPersistTocLinkProgress_Success tests ToC link progress persistence.
func TestPersistTocLinkProgress_Success(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book1", map[string]any{})

	book := NewBookState("book1")
	book.Store = store
	book.SetTocLinkProgress(20, 15)

	err := book.PersistTocLinkProgress(context.Background())
	if err != nil {
		t.Fatalf("PersistTocLinkProgress error: %v", err)
	}

	// Verify DB was updated
	doc := store.GetDoc("Book", "book1")
	if doc["toc_link_entries_total"] != 20 {
		t.Errorf("toc_link_entries_total = %v, want 20", doc["toc_link_entries_total"])
	}
	if doc["toc_link_entries_done"] != 15 {
		t.Errorf("toc_link_entries_done = %v, want 15", doc["toc_link_entries_done"])
	}
}
