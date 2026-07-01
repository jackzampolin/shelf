package job

import (
	"context"
	"fmt"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func newOcrSkipJob() (*Job, *common.BookState) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableOCR = true
	book.OcrProviders = []string{"chandra-local"}
	book.TotalPages = 12
	book.GetOrCreatePage(12)

	return NewFromLoadResult(&common.LoadBookResult{Book: book}), book
}

// A pathological page that exhausts its OCR retries must be skipped (recorded as
// resolved with no text, like a blank page) so the rest of the book still
// processes. It must NOT return a fatal error, which the scheduler treats as
// "kill the whole book".
func TestOnCompleteOcrFailureAfterRetriesSkipsPageAndContinues(t *testing.T) {
	j, book := newOcrSkipJob()

	const unitID = "wu-ocr-12"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeOCR,
		PageNum:    12,
		Provider:   "chandra-local",
		RetryCount: MaxOCRPageRetries, // retries already exhausted
	})

	units, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("context deadline exceeded"),
	})

	if err != nil {
		t.Fatalf("OnComplete returned a fatal error for a page that exhausted OCR retries; want nil so the book continues: %v", err)
	}
	if len(units) != 0 {
		t.Fatalf("expected no new work units after giving up on the page, got %d", len(units))
	}

	page := book.GetPage(12)
	if page == nil || !page.OcrComplete("chandra-local") {
		t.Fatal("page 12 should be marked OCR-resolved after giving up, so the book is not blocked on it")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed OCR work unit should be removed after giving up on it")
	}
}

// A page whose image extraction exhausts its retries cannot be OCR'd, so it must
// be skipped (resolved as a blank page) rather than failing the whole book. With
// thousands of pages, pathological/corrupt PDF pages are common; one must not be
// fatal.
func TestOnCompleteExtractFailureAfterRetriesSkipsPageAndContinues(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableOCR = true
	book.OcrProviders = []string{"chandra-local"}
	book.TotalPages = 10
	book.GetOrCreatePage(5)

	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	const unitID = "wu-extract-5"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeExtract,
		PageNum:    5,
		RetryCount: MaxPageOpRetries, // retries exhausted
	})

	_, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("failed to extract page image: corrupt page"),
	})
	if err != nil {
		t.Fatalf("OnComplete returned a fatal error for a page that exhausted extract retries; want nil so the book continues: %v", err)
	}

	page := book.GetPage(5)
	if page == nil || !page.IsExtractDone() {
		t.Fatal("page 5 should be marked extract-done after giving up, so extract is not re-emitted")
	}
	if !page.OcrComplete("chandra-local") {
		t.Fatal("page 5 should be OCR-resolved (no image to OCR) so the OCR stage can complete")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed extract work unit should be removed after giving up on it")
	}
}

// Skipping a page resolves its OCR, so if that page is the one that crosses a
// downstream threshold, the skip must trigger the next book operation exactly
// like a successful OCR would. Otherwise a book whose last gating page is
// pathological stalls with OCR "done" but nothing downstream ever starting.
func TestOnCompleteOcrSkipTriggersDownstreamBookOperations(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableOCR = true
	book.EnableMetadata = true
	book.OcrProviders = []string{"chandra-local"}
	book.MetadataProvider = "qwen-local"
	book.TotalPages = 30

	// The metadata threshold (20 pages) is already satisfied by real OCR'd pages,
	// but metadata has not been started yet because no completion event has fired
	// MaybeStartBookOperations. The pathological page is page 21.
	for p := 1; p <= OcrThresholdForMetadata; p++ {
		ps := book.GetOrCreatePage(p)
		ps.MarkOcrComplete("chandra-local", "Some OCR text for the page.")
		ps.SetOcrMarkdown("Some OCR text for the page.")
	}
	pathologicalPage := OcrThresholdForMetadata + 1
	book.GetOrCreatePage(pathologicalPage)

	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	const unitID = "wu-ocr-21"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeOCR,
		PageNum:    pathologicalPage,
		Provider:   "chandra-local",
		RetryCount: MaxOCRPageRetries,
	})

	units, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("context deadline exceeded"),
	})
	if err != nil {
		t.Fatalf("OnComplete returned a fatal error skipping the page: %v", err)
	}

	if !j.Book.MetadataIsStarted() {
		t.Fatal("skipping the page that crosses the OCR threshold should trigger downstream book operations (metadata)")
	}
	if len(units) == 0 {
		t.Fatal("skip should return the triggered downstream work unit")
	}
}
