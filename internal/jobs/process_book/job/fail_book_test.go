package job

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestFailBookPersistsFailedStatusWithReason(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	j.FailBook(context.Background(), "work unit failed (finalize_discover): context length")

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != string(BookStatusFailed) {
		t.Fatalf("status = %v, want %v", doc["status"], BookStatusFailed)
	}
	if doc["status_reason"] != "work unit failed (finalize_discover): context length" {
		t.Fatalf("status_reason = %v", doc["status_reason"])
	}
}
