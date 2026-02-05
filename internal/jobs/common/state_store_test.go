package common

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
)

// TestMemoryStateStore_SendManySync tests batch write operations.
func TestMemoryStateStore_SendManySync(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Test empty ops
	results, err := store.SendManySync(ctx, nil)
	if err != nil {
		t.Fatalf("SendManySync(nil) error = %v", err)
	}
	if results != nil {
		t.Errorf("SendManySync(nil) results = %v, want nil", results)
	}

	// Test multiple creates
	ops := []defra.WriteOp{
		{Collection: "Page", Document: map[string]any{"page_num": 1, "book_id": "book1"}, Op: defra.OpCreate},
		{Collection: "Page", Document: map[string]any{"page_num": 2, "book_id": "book1"}, Op: defra.OpCreate},
		{Collection: "Page", Document: map[string]any{"page_num": 3, "book_id": "book1"}, Op: defra.OpCreate},
	}

	results, err = store.SendManySync(ctx, ops)
	if err != nil {
		t.Fatalf("SendManySync error = %v", err)
	}
	if len(results) != 3 {
		t.Fatalf("SendManySync results len = %d, want 3", len(results))
	}

	// Verify each result has DocID and CID
	for i, r := range results {
		if r.DocID == "" {
			t.Errorf("results[%d].DocID is empty", i)
		}
		if r.CID == "" {
			t.Errorf("results[%d].CID is empty", i)
		}
	}

	// Verify writes were tracked
	if store.WriteCount() != 3 {
		t.Errorf("WriteCount() = %d, want 3", store.WriteCount())
	}

	// Verify docs exist in store
	for _, r := range results {
		doc := store.GetDoc("Page", r.DocID)
		if doc == nil {
			t.Errorf("Doc %s not found in store", r.DocID)
		}
	}
}

// TestMemoryStateStore_UpsertWithVersion tests upsert operations.
func TestMemoryStateStore_UpsertWithVersion(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Test create (no existing doc)
	filter := map[string]any{"unique_key": "ch1"}
	createInput := map[string]any{"unique_key": "ch1", "title": "Chapter 1", "book_id": "book1"}
	updateInput := map[string]any{"title": "Chapter 1 Updated"}

	result, err := store.UpsertWithVersion(ctx, "Chapter", filter, createInput, updateInput)
	if err != nil {
		t.Fatalf("UpsertWithVersion (create) error = %v", err)
	}
	if result.DocID == "" {
		t.Error("UpsertWithVersion (create) DocID is empty")
	}
	if result.CID == "" {
		t.Error("UpsertWithVersion (create) CID is empty")
	}

	// Verify doc was created with createInput
	doc := store.GetDoc("Chapter", result.DocID)
	if doc == nil {
		t.Fatal("Doc not found after create")
	}
	if doc["title"] != "Chapter 1" {
		t.Errorf("title = %v, want 'Chapter 1'", doc["title"])
	}
	if doc["unique_key"] != "ch1" {
		t.Errorf("unique_key = %v, want 'ch1'", doc["unique_key"])
	}

	firstDocID := result.DocID
	firstCID := result.CID

	// Test update (existing doc matches filter)
	result2, err := store.UpsertWithVersion(ctx, "Chapter", filter, createInput, updateInput)
	if err != nil {
		t.Fatalf("UpsertWithVersion (update) error = %v", err)
	}
	if result2.DocID != firstDocID {
		t.Errorf("UpsertWithVersion (update) DocID = %s, want %s (same doc)", result2.DocID, firstDocID)
	}
	if result2.CID == firstCID {
		t.Error("UpsertWithVersion (update) CID should be different from first CID")
	}

	// Verify doc was updated with updateInput
	doc = store.GetDoc("Chapter", result2.DocID)
	if doc["title"] != "Chapter 1 Updated" {
		t.Errorf("title after update = %v, want 'Chapter 1 Updated'", doc["title"])
	}
	// unique_key should still be there
	if doc["unique_key"] != "ch1" {
		t.Errorf("unique_key after update = %v, want 'ch1'", doc["unique_key"])
	}
}

// TestMemoryStateStore_UpdateWithVersion tests update operations.
func TestMemoryStateStore_UpdateWithVersion(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Create a doc first
	store.SetDoc("Book", "book1", map[string]any{
		"title":  "Original Title",
		"status": "pending",
	})

	// Update the doc
	result, err := store.UpdateWithVersion(ctx, "Book", "book1", map[string]any{
		"status": "processing",
	})
	if err != nil {
		t.Fatalf("UpdateWithVersion error = %v", err)
	}
	if result.DocID != "book1" {
		t.Errorf("UpdateWithVersion DocID = %s, want 'book1'", result.DocID)
	}
	if result.CID == "" {
		t.Error("UpdateWithVersion CID is empty")
	}

	// Verify doc was updated
	doc := store.GetDoc("Book", "book1")
	if doc["status"] != "processing" {
		t.Errorf("status = %v, want 'processing'", doc["status"])
	}
	// Original field should still be there
	if doc["title"] != "Original Title" {
		t.Errorf("title = %v, want 'Original Title'", doc["title"])
	}

	// Update again and verify CID changes
	result2, err := store.UpdateWithVersion(ctx, "Book", "book1", map[string]any{
		"status": "complete",
	})
	if err != nil {
		t.Fatalf("UpdateWithVersion (2nd) error = %v", err)
	}
	if result2.CID == result.CID {
		t.Error("UpdateWithVersion CID should change between updates")
	}
}

// TestMemoryStateStore_CIDGeneration tests that CIDs are unique and consistent.
func TestMemoryStateStore_CIDGeneration(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Multiple updates to same doc should generate increasing CIDs
	store.SetDoc("Book", "book1", map[string]any{"title": "Test"})

	var cids []string
	for i := 0; i < 5; i++ {
		result, err := store.UpdateWithVersion(ctx, "Book", "book1", map[string]any{
			"iteration": i,
		})
		if err != nil {
			t.Fatalf("UpdateWithVersion error = %v", err)
		}
		cids = append(cids, result.CID)
	}

	// All CIDs should be unique
	seen := make(map[string]bool)
	for _, cid := range cids {
		if seen[cid] {
			t.Errorf("Duplicate CID: %s", cid)
		}
		seen[cid] = true
	}
}

// TestMemoryStateStore_SendSync_ReturnsCID tests that SendSync returns CID.
func TestMemoryStateStore_SendSync_ReturnsCID(t *testing.T) {
	store := NewMemoryStateStore()
	ctx := context.Background()

	// Create
	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		Document:   map[string]any{"title": "Test"},
		Op:         defra.OpCreate,
	})
	if err != nil {
		t.Fatalf("SendSync error = %v", err)
	}
	if result.DocID == "" {
		t.Error("SendSync DocID is empty")
	}
	if result.CID == "" {
		t.Error("SendSync CID is empty")
	}

	// Update
	result2, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      result.DocID,
		Document:   map[string]any{"status": "updated"},
		Op:         defra.OpUpdate,
	})
	if err != nil {
		t.Fatalf("SendSync (update) error = %v", err)
	}
	if result2.CID == "" {
		t.Error("SendSync (update) CID is empty")
	}
	if result2.CID == result.CID {
		t.Error("SendSync CID should change between create and update")
	}
}

// TestMemoryStateStore_ErrorInjection tests error injection functionality.
func TestMemoryStateStore_ErrorInjection(t *testing.T) {
	ctx := context.Background()

	t.Run("ExecuteErr", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.ExecuteErr = errTest

		_, err := store.Execute(ctx, `{ Book { _docID } }`, nil)
		if err != errTest {
			t.Errorf("Execute error = %v, want %v", err, errTest)
		}
	})

	t.Run("SendSyncErr", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SendSyncErr = errTest

		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "Book",
			Document:   map[string]any{"title": "Test"},
			Op:         defra.OpCreate,
		})
		if err != errTest {
			t.Errorf("SendSync error = %v, want %v", err, errTest)
		}
	})

	t.Run("ErrOnCollection", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetErrorOnCollection("Chapter", errTest)

		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "Chapter",
			Document:   map[string]any{"title": "Test"},
			Op:         defra.OpCreate,
		})
		if err != errTest {
			t.Errorf("SendSync error = %v, want %v", err, errTest)
		}

		// Book should still work
		_, err = store.SendSync(ctx, defra.WriteOp{
			Collection: "Book",
			Document:   map[string]any{"title": "Test"},
			Op:         defra.OpCreate,
		})
		if err != nil {
			t.Errorf("SendSync to Book error = %v, want nil", err)
		}
	})

	t.Run("ErrOnDocID", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetDoc("Book", "book1", map[string]any{"title": "Test"})
		store.SetErrorOnDocID("Book", "book1", errTest)

		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "Book",
			DocID:      "book1",
			Document:   map[string]any{"status": "updated"},
			Op:         defra.OpUpdate,
		})
		if err != errTest {
			t.Errorf("SendSync error = %v, want %v", err, errTest)
		}

		// Other docs should work
		_, err = store.SendSync(ctx, defra.WriteOp{
			Collection: "Book",
			DocID:      "book2",
			Document:   map[string]any{"status": "updated"},
			Op:         defra.OpUpdate,
		})
		if err != nil {
			t.Errorf("SendSync to book2 error = %v, want nil", err)
		}
	})

	t.Run("ErrAfterNWrites", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetErrorAfterNWrites(2)

		// First two should succeed
		for i := 0; i < 2; i++ {
			_, err := store.SendSync(ctx, defra.WriteOp{
				Collection: "Book",
				Document:   map[string]any{"n": i},
				Op:         defra.OpCreate,
			})
			if err != nil {
				t.Errorf("SendSync #%d error = %v, want nil", i+1, err)
			}
		}

		// Third should fail
		_, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "Book",
			Document:   map[string]any{"n": 3},
			Op:         defra.OpCreate,
		})
		if err == nil {
			t.Error("SendSync #3 should have failed")
		}
	})

	t.Run("SendManySyncPartialFailure", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.SetErrorOnCollection("Chapter", errTest)

		ops := []defra.WriteOp{
			{Collection: "Book", Document: map[string]any{"title": "Test"}, Op: defra.OpCreate},
			{Collection: "Chapter", Document: map[string]any{"title": "Ch1"}, Op: defra.OpCreate},
			{Collection: "Book", Document: map[string]any{"title": "Test2"}, Op: defra.OpCreate},
		}

		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			t.Fatalf("SendManySync error = %v, want nil (individual errors in results)", err)
		}
		if len(results) != 3 {
			t.Fatalf("results len = %d, want 3", len(results))
		}

		// First should succeed
		if results[0].Err != nil {
			t.Errorf("results[0].Err = %v, want nil", results[0].Err)
		}
		// Second (Chapter) should have error
		if results[1].Err != errTest {
			t.Errorf("results[1].Err = %v, want %v", results[1].Err, errTest)
		}
		// Third should succeed
		if results[2].Err != nil {
			t.Errorf("results[2].Err = %v, want nil", results[2].Err)
		}
	})

	t.Run("ClearErrors", func(t *testing.T) {
		store := NewMemoryStateStore()
		store.ExecuteErr = errTest
		store.SendSyncErr = errTest
		store.SetErrorOnCollection("Book", errTest)

		store.ClearErrors()

		// All operations should work now
		_, err := store.Execute(ctx, `{ Book { _docID } }`, nil)
		if err != nil {
			t.Errorf("Execute after ClearErrors = %v, want nil", err)
		}

		_, err = store.SendSync(ctx, defra.WriteOp{
			Collection: "Book",
			Document:   map[string]any{"title": "Test"},
			Op:         defra.OpCreate,
		})
		if err != nil {
			t.Errorf("SendSync after ClearErrors = %v, want nil", err)
		}
	})
}

// TestNewDefraStateStore tests the constructor validation.
func TestNewDefraStateStore(t *testing.T) {
	t.Run("nil client", func(t *testing.T) {
		_, err := NewDefraStateStore(nil, &defra.Sink{})
		if err == nil {
			t.Error("NewDefraStateStore(nil, sink) should return error")
		}
	})

	t.Run("nil sink", func(t *testing.T) {
		_, err := NewDefraStateStore(&defra.Client{}, nil)
		if err == nil {
			t.Error("NewDefraStateStore(client, nil) should return error")
		}
	})

	t.Run("valid", func(t *testing.T) {
		store, err := NewDefraStateStore(&defra.Client{}, &defra.Sink{})
		if err != nil {
			t.Errorf("NewDefraStateStore error = %v, want nil", err)
		}
		if store == nil {
			t.Error("NewDefraStateStore returned nil store")
		}
	})
}

// errTest is a test error for error injection tests.
var errTest = defra.WriteResult{}.Err // Will be nil, need a real error

func init() {
	// Initialize errTest with a real error
	errTest = &testError{"injected test error"}
}

type testError struct {
	msg string
}

func (e *testError) Error() string {
	return e.msg
}
