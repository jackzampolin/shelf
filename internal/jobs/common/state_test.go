package common

import (
	"sync"
	"testing"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
)

// TestBookState_ConcurrentAccess tests thread-safety of BookState accessor methods.
func TestBookState_ConcurrentAccess(t *testing.T) {
	t.Run("concurrent_operation_state_transitions", func(t *testing.T) {
		book := NewBookState("test-book")

		// Run concurrent operations on operation state
		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		// Test concurrent metadata state access
		wg.Add(numGoroutines * 2) // readers and writers

		// Writers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					if book.MetadataCanStart() {
						book.MetadataStart()
					}
					if book.MetadataIsStarted() {
						book.MetadataComplete()
					}
					book.MetadataReset()
				}
			}()
		}

		// Readers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					_ = book.MetadataCanStart()
					_ = book.MetadataIsStarted()
					_ = book.MetadataIsDone()
					_ = book.GetMetadataState()
				}
			}()
		}

		wg.Wait()
		// Test passes if no race conditions detected (run with -race flag)
	})

	t.Run("concurrent_toc_entries_access", func(t *testing.T) {
		book := NewBookState("test-book")

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		wg.Add(numGoroutines * 2)

		// Writers - set entries
		for i := 0; i < numGoroutines; i++ {
			go func(id int) {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					entries := []*toc_entry_finder.TocEntry{
						{DocID: "entry1", Title: "Chapter 1", SortOrder: 1},
						{DocID: "entry2", Title: "Chapter 2", SortOrder: 2},
					}
					book.SetTocEntries(entries)
				}
			}(i)
		}

		// Readers - get entries (should get a copy of the slice)
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					entries := book.GetTocEntries()
					// The slice is a copy, but the pointers inside point to the same entries
					// (shallow copy - intentional for performance)
					// Verify we can read without panicking
					_ = len(entries)
					if len(entries) > 0 {
						_ = entries[0].Title // read-only access
					}
				}
			}()
		}

		wg.Wait()
	})

	t.Run("concurrent_structure_chapters_access", func(t *testing.T) {
		book := NewBookState("test-book")

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		wg.Add(numGoroutines * 2)

		// Writers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					chapters := []*ChapterState{
						{EntryID: "ch1", Title: "Chapter 1", StartPage: 1},
						{EntryID: "ch2", Title: "Chapter 2", StartPage: 10},
					}
					book.SetStructureChapters(chapters)
				}
			}()
		}

		// Readers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					chapters := book.GetStructureChapters()
					_ = len(chapters)
				}
			}()
		}

		wg.Wait()
	})

	t.Run("concurrent_agent_state_access", func(t *testing.T) {
		book := NewBookState("test-book")

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		wg.Add(numGoroutines * 3) // writers, readers, deleters

		// Writers - set agent states
		for i := 0; i < numGoroutines; i++ {
			go func(id int) {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					state, err := NewAgentState(AgentTypeTocFinder, "agent-test")
					if err != nil {
						continue
					}
					book.SetAgentState(state)
				}
			}(i)
		}

		// Readers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					_ = book.GetAgentState(AgentTypeTocFinder, "")
					_ = book.GetAllAgentStates()
				}
			}()
		}

		// Deleters
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					book.ClearAgentStates(AgentTypeTocFinder)
				}
			}()
		}

		wg.Wait()
	})

	t.Run("concurrent_classifications_access", func(t *testing.T) {
		book := NewBookState("test-book")

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		wg.Add(numGoroutines * 2)

		// Writers - set classifications
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					classifications := map[string]string{
						"ch1": "body",
						"ch2": "front_matter",
					}
					book.SetStructureClassifications(classifications)

					reasonings := map[string]string{
						"ch1": "Main content",
						"ch2": "Preface",
					}
					book.SetStructureClassifyReasonings(reasonings)
				}
			}()
		}

		// Readers - get copies
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					classifications := book.GetStructureClassifications()
					// Modify returned map - should not affect internal state
					if classifications != nil {
						classifications["modified"] = "test"
					}

					reasonings := book.GetStructureClassifyReasonings()
					if reasonings != nil {
						reasonings["modified"] = "test"
					}
				}
			}()
		}

		wg.Wait()
	})
}

// TestPageState_ConcurrentAccess tests thread-safety of PageState accessor methods.
func TestPageState_ConcurrentAccess(t *testing.T) {
	t.Run("concurrent_ocr_results", func(t *testing.T) {
		page := NewPageState()

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		providers := []string{"openrouter", "mistral", "deepinfra"}

		wg.Add(numGoroutines * 2)

		// Writers - mark OCR complete
		for i := 0; i < numGoroutines; i++ {
			go func(id int) {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					provider := providers[j%len(providers)]
					page.MarkOcrComplete(provider, "OCR result text")
				}
			}(i)
		}

		// Readers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					for _, p := range providers {
						_ = page.OcrComplete(p)
					}
				}
			}()
		}

		wg.Wait()
	})

	t.Run("concurrent_headings_access", func(t *testing.T) {
		page := NewPageState()

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		wg.Add(numGoroutines * 2)

		// Writers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					headings := []HeadingItem{
						{Text: "Heading 1", Level: 1},
						{Text: "Heading 2", Level: 2},
					}
					page.SetHeadings(headings)
				}
			}()
		}

		// Readers - get copies
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					headings := page.GetHeadings()
					// Modify returned slice - should not affect internal state
					if len(headings) > 0 {
						headings[0].Text = "modified"
					}
				}
			}()
		}

		wg.Wait()
	})

	t.Run("concurrent_blend_operations", func(t *testing.T) {
		page := NewPageState()

		var wg sync.WaitGroup
		const numGoroutines = 10
		const numIterations = 100

		wg.Add(numGoroutines * 2)

		// Writers
		for i := 0; i < numGoroutines; i++ {
			go func(id int) {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					page.SetBlendResult("blended text content")
				}
			}(i)
		}

		// Readers
		for i := 0; i < numGoroutines; i++ {
			go func() {
				defer wg.Done()
				for j := 0; j < numIterations; j++ {
					_ = page.GetBlendedText()
					_ = page.IsBlendDone()
				}
			}()
		}

		wg.Wait()
	})
}

// TestGetHeadings_ReturnsCopy verifies that GetHeadings returns a copy, not the original slice.
func TestGetHeadings_ReturnsCopy(t *testing.T) {
	page := NewPageState()

	original := []HeadingItem{
		{Text: "Original Heading", Level: 1},
	}
	page.SetHeadings(original)

	// Get a copy
	copy1 := page.GetHeadings()
	if copy1 == nil {
		t.Fatal("GetHeadings returned nil")
	}

	// Modify the copy
	copy1[0].Text = "Modified"

	// Get another copy and verify original is unchanged
	copy2 := page.GetHeadings()
	if copy2[0].Text != "Original Heading" {
		t.Errorf("internal state was modified: got %s, want 'Original Heading'", copy2[0].Text)
	}
}

// TestGetStructureClassifyReasonings_ReturnsCopy verifies that GetStructureClassifyReasonings
// returns a copy, not the original map.
func TestGetStructureClassifyReasonings_ReturnsCopy(t *testing.T) {
	book := &BookState{
		BookID:    "test-book",
		BookDocID: "test-book",
		Pages:     make(map[int]*PageState),
	}

	original := map[string]string{
		"ch1": "Original reasoning",
	}
	book.SetStructureClassifyReasonings(original)

	// Get a copy
	copy1 := book.GetStructureClassifyReasonings()
	if copy1 == nil {
		t.Fatal("GetStructureClassifyReasonings returned nil")
	}

	// Modify the copy
	copy1["ch1"] = "Modified"
	copy1["ch2"] = "New entry"

	// Get another copy and verify original is unchanged
	copy2 := book.GetStructureClassifyReasonings()
	if copy2["ch1"] != "Original reasoning" {
		t.Errorf("internal state was modified: got %s, want 'Original reasoning'", copy2["ch1"])
	}
	if _, exists := copy2["ch2"]; exists {
		t.Error("internal map was modified: ch2 should not exist")
	}
}

// TestOperationState_StateMachine tests the operation state machine transitions.
func TestOperationState_StateMachine(t *testing.T) {
	t.Run("valid_transitions", func(t *testing.T) {
		op := OperationState{}

		// Initial state
		if !op.CanStart() {
			t.Error("should be able to start from initial state")
		}
		if op.IsStarted() {
			t.Error("should not be started initially")
		}

		// Start
		if err := op.Start(); err != nil {
			t.Errorf("Start() error = %v", err)
		}
		if !op.IsStarted() {
			t.Error("should be started after Start()")
		}
		if op.CanStart() {
			t.Error("should not be able to start when already started")
		}

		// Complete
		op.Complete()
		if !op.IsDone() {
			t.Error("should be done after Complete()")
		}
		if !op.IsComplete() {
			t.Error("should be complete after Complete()")
		}
		if op.IsFailed() {
			t.Error("should not be failed after Complete()")
		}
	})

	t.Run("fail_with_retries", func(t *testing.T) {
		op := OperationState{}
		_ = op.Start()

		// Fail with retries remaining (retries >= maxRetries triggers failure)
		// With maxRetries=3: fails when retries reaches 3 (0, 1, 2 are ok)
		op.Fail(3) // retries=1, 1 >= 3 is false -> not failed
		if op.IsFailed() {
			t.Error("should not be failed after first fail")
		}
		if !op.CanStart() {
			t.Error("should be able to start after fail with retries")
		}

		// Try again and fail
		_ = op.Start()
		op.Fail(3) // retries=2, 2 >= 3 is false -> not failed
		if op.IsFailed() {
			t.Error("should not be failed after second fail")
		}

		// Third fail - should be failed now
		_ = op.Start()
		op.Fail(3) // retries=3, 3 >= 3 is true -> failed
		if !op.IsFailed() {
			t.Error("should be failed after maxRetries exhausted")
		}
	})

	t.Run("reset", func(t *testing.T) {
		op := OperationState{}
		_ = op.Start()
		op.Complete()

		op.Reset()
		if !op.CanStart() {
			t.Error("should be able to start after Reset()")
		}
		if op.IsDone() {
			t.Error("should not be done after Reset()")
		}
	})

	t.Run("double_start_error", func(t *testing.T) {
		op := OperationState{}
		_ = op.Start()

		err := op.Start()
		if err == nil {
			t.Error("double Start() should return error")
		}
	})
}

// TestAgentState_Validation tests AgentState creation and validation.
func TestAgentState_Validation(t *testing.T) {
	t.Run("valid_agent_types", func(t *testing.T) {
		validTypes := []string{
			AgentTypeTocFinder,
			AgentTypeTocEntryFinder,
			AgentTypeChapterFinder,
			AgentTypeGapInvestigator,
		}

		for _, agentType := range validTypes {
			state, err := NewAgentState(agentType, "test-id")
			if err != nil {
				t.Errorf("NewAgentState(%s) error = %v", agentType, err)
			}
			if state == nil {
				t.Errorf("NewAgentState(%s) returned nil", agentType)
			}
		}
	})

	t.Run("invalid_agent_type", func(t *testing.T) {
		_, err := NewAgentState("invalid_type", "test-id")
		if err == nil {
			t.Error("NewAgentState with invalid type should return error")
		}
	})

	t.Run("empty_agent_id", func(t *testing.T) {
		_, err := NewAgentState(AgentTypeTocFinder, "")
		if err == nil {
			t.Error("NewAgentState with empty ID should return error")
		}
	})

	t.Run("is_valid_agent_type", func(t *testing.T) {
		if !IsValidAgentType(AgentTypeTocFinder) {
			t.Error("toc_finder should be valid")
		}
		if IsValidAgentType("invalid") {
			t.Error("invalid should not be valid")
		}
	})
}

// TestChapterState_Validation tests ChapterState creation and validation.
// NewChapterState signature: (entryID, uniqueKey, title string, startPage int)
func TestChapterState_Validation(t *testing.T) {
	t.Run("valid_chapter", func(t *testing.T) {
		// NewChapterState(entryID, uniqueKey, title, startPage)
		ch, err := NewChapterState("entry1", "book1:entry1", "Chapter 1", 10)
		if err != nil {
			t.Fatalf("NewChapterState() error = %v", err)
		}
		if ch.EntryID != "entry1" {
			t.Errorf("EntryID = %s, want entry1", ch.EntryID)
		}
		if ch.UniqueKey != "book1:entry1" {
			t.Errorf("UniqueKey = %s, want book1:entry1", ch.UniqueKey)
		}
		if ch.StartPage != 10 {
			t.Errorf("StartPage = %d, want 10", ch.StartPage)
		}
	})

	t.Run("invalid_start_page", func(t *testing.T) {
		_, err := NewChapterState("entry1", "book1:entry1", "Chapter 1", 0)
		if err == nil {
			t.Error("NewChapterState with start_page=0 should return error")
		}

		_, err = NewChapterState("entry1", "book1:entry1", "Chapter 1", -1)
		if err == nil {
			t.Error("NewChapterState with negative start_page should return error")
		}
	})

	t.Run("empty_required_fields", func(t *testing.T) {
		_, err := NewChapterState("", "book1:entry1", "Chapter 1", 1)
		if err == nil {
			t.Error("NewChapterState with empty entryID should return error")
		}

		_, err = NewChapterState("entry1", "", "Chapter 1", 1)
		if err == nil {
			t.Error("NewChapterState with empty uniqueKey should return error")
		}

		_, err = NewChapterState("entry1", "book1:entry1", "", 1)
		if err == nil {
			t.Error("NewChapterState with empty title should return error")
		}
	})
}
