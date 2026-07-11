package job

import (
	"context"
	"fmt"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// A ToC entry that cannot be linked after its retries are exhausted must fail
// visibly. It must not be counted as resolved or allow finalize/structure to
// turn a degraded book into a successful terminal result.
func TestOnCompleteTocLinkFailureAfterRetriesFailsClosed(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})
	store.SetDoc("ToC", "toc-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableTocLink = true
	book.EnableTocFinalize = false
	book.EnableStructure = false
	book.SetTocDocID("toc-1")
	book.SetOpState(common.OpTocExtract, false, true, false, 0) // extract done
	book.SetOpState(common.OpTocLink, true, false, false, 0)    // link in progress
	book.SetTocLinkProgress(1, 0)                               // 1 entry, 0 resolved

	j := NewFromLoadResult(&common.LoadBookResult{Book: book, TocDocID: "toc-1"})

	const unitID = "wu-link-1"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeLinkToc,
		EntryDocID: "entry-1",
		RetryCount: MaxBookOpRetries, // retries exhausted
	})

	_, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("agent did not complete within 25 iterations"),
	})

	if err == nil {
		t.Fatal("OnComplete returned nil for an exhausted ToC entry; want actionable terminal failure")
	}
	if got := err.Error(); got == "" || !strings.Contains(got, "entry-1") {
		t.Fatalf("terminal error = %q, want entry ID", got)
	}

	total, done := j.Book.GetTocLinkProgress()
	if done != 0 || total != 1 {
		t.Fatalf("ToC link progress = %d/%d, want 0/1 (failed entry unresolved)", done, total)
	}
	linkState := j.Book.GetTocLinkState()
	if linkState.IsComplete() || !linkState.IsFailed() {
		t.Fatalf("ToC link state = %#v, want failed and incomplete", linkState)
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed link work unit should be removed after giving up on the entry")
	}
	entry := store.GetDoc("TocEntry", "entry-1")
	if entry["link_failed"] != true || entry["link_retries"] != MaxBookOpRetries {
		t.Fatalf("terminal entry state = %#v", entry)
	}
	if entry["link_failure_reason"] != "agent did not complete within 25 iterations" || entry["link_failed_at"] == "" {
		t.Fatalf("terminal entry provenance = %#v", entry)
	}
}
