package job

import (
	"context"
	"fmt"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// A ToC entry that cannot be linked after its retries are exhausted must be
// skipped (counted as resolved) so the link stage can complete and the book
// proceeds to finalize/structure. One stubborn entry must NOT kill a book whose
// other entries linked fine — returning a fatal error makes the scheduler kill
// the whole job.
func TestOnCompleteTocLinkFailureAfterRetriesSkipsEntryAndCompletes(t *testing.T) {
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

	if err != nil {
		t.Fatalf("OnComplete returned a fatal error for an unlinkable ToC entry; want nil so the book continues: %v", err)
	}

	total, done := j.Book.GetTocLinkProgress()
	if done != 1 || total != 1 {
		t.Fatalf("ToC link progress = %d/%d, want 1/1 (skipped entry counted resolved)", done, total)
	}
	linkState := j.Book.GetTocLinkState()
	if !linkState.IsComplete() {
		t.Fatal("ToC link should complete after the last entry is skipped, so finalize/structure can run")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed link work unit should be removed after giving up on the entry")
	}
}
