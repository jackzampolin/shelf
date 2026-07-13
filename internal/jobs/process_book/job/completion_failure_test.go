package job

import (
	"context"
	"strings"
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

func TestCheckCompletionMarksQuarantinedBookDegraded(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableOCR = true
	book.OcrProviders = []string{"chandra-local"}
	book.TotalPages = 1
	book.GetOrCreatePage(1).QuarantineOCR("image-only map")

	j := NewFromLoadResult(&common.LoadBookResult{Book: book})
	j.CheckCompletion(context.Background())

	if !j.Done() {
		t.Fatal("quarantined book should be terminal for scheduling")
	}
	doc := store.GetDoc("Book", "book-1")
	if got := doc["status"]; got != string(BookStatusDegraded) {
		t.Fatalf("book status = %v, want degraded", got)
	}
	if reason, _ := doc["status_reason"].(string); !strings.Contains(reason, "page=1") {
		t.Fatalf("status_reason = %q, want actionable quarantined page", reason)
	}
}

func TestCompleteStructureRejectsPolishFallback(t *testing.T) {
	book := common.NewBookState("book-1")
	book.IncrementStructurePolishFailed()
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	if _, err := j.completeStructurePhase(context.Background()); err == nil || !strings.Contains(err.Error(), "not certifiable") {
		t.Fatalf("completeStructurePhase() error = %v, want non-certifiable polish failure", err)
	}
	if book.StructureIsComplete() {
		t.Fatal("structure completed despite a failed chapter polish")
	}
}
