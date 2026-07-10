package job

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestCheckCompletionRejectsPermanentlyFailedRequiredStage(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableStructure = true
	book.EnableTocFinalize = true
	book.SetOpState(common.OpTocFinalize, false, true, false, 0)
	book.SetOpState(common.OpStructure, false, false, true, MaxBookOpRetries)

	j := NewFromLoadResult(&common.LoadBookResult{Book: book})
	j.CheckCompletion(context.Background())

	if j.Done() {
		t.Fatal("job completed despite a permanently failed required structure stage")
	}
	if reason := j.NoWorkFailure(); reason != "structure phase failed after retries" {
		t.Fatalf("NoWorkFailure() = %q, want actionable structure failure", reason)
	}
	if got := store.GetDoc("Book", "book-1")["status"]; got == string(BookStatusComplete) {
		t.Fatal("book was persisted complete despite structure failure")
	}
}
