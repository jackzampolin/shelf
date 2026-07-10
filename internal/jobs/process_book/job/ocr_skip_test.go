package job

import (
	"context"
	"fmt"
	"os"
	"testing"

	"github.com/jackzampolin/shelf/internal/home"
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

// An exhausted infrastructure failure must fail visibly without resolving the
// page. Persisting it as a blank page silently corrupts the book and prevents a
// durable retry from re-emitting the failed page.
func TestOnCompleteOcrInfrastructureFailureAfterRetriesFailsWithoutResolvingPage(t *testing.T) {
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

	if err == nil {
		t.Fatal("OnComplete error = nil, want infrastructure failure to fail the job visibly")
	}
	if len(units) != 0 {
		t.Fatalf("expected no new work units after fatal infrastructure failure, got %d", len(units))
	}

	page := book.GetPage(12)
	if page == nil {
		t.Fatal("page 12 is missing")
	}
	if page.OcrComplete("chandra-local") {
		t.Fatal("page 12 must remain incomplete so a durable retry re-emits it")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed OCR work unit should be removed when the job fails")
	}
}

func TestStartAfterOcrInfrastructureFailureReemitsOnlyIncompletePage(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	homeDir, err := home.New(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	if err := homeDir.EnsureSourceImagesDir("book-1"); err != nil {
		t.Fatal(err)
	}
	for pageNum := 1; pageNum <= 2; pageNum++ {
		if err := os.WriteFile(homeDir.SourceImagePath("book-1", pageNum), []byte("png"), 0o600); err != nil {
			t.Fatal(err)
		}
	}

	book := common.NewBookState("book-1")
	book.Store = store
	book.HomeDir = homeDir
	book.EnableOCR = true
	book.OcrProviders = []string{"chandra-local"}
	book.TotalPages = 2

	complete := book.GetOrCreatePage(1)
	complete.SetPageDocID("page-1")
	complete.SetExtractDone(true)
	complete.MarkOcrComplete("chandra-local", "good OCR")
	incomplete := book.GetOrCreatePage(2)
	incomplete.SetPageDocID("page-2")
	incomplete.SetExtractDone(true)

	failedJob := NewFromLoadResult(&common.LoadBookResult{Book: book})
	const unitID = "wu-ocr-infra-page-2"
	failedJob.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeOCR,
		PageNum:    2,
		Provider:   "chandra-local",
		RetryCount: MaxOCRPageRetries,
	})
	if _, err := failedJob.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("Client.Timeout exceeded while awaiting headers"),
	}); err == nil {
		t.Fatal("infrastructure exhaustion should fail the first job")
	}

	resumedJob := NewFromLoadResult(&common.LoadBookResult{Book: book})
	units, err := resumedJob.Start(context.Background())
	if err != nil {
		t.Fatalf("Start after infrastructure failure: %v", err)
	}
	if len(units) != 1 {
		t.Fatalf("Start emitted %d work units, want only the incomplete page", len(units))
	}
	info, ok := resumedJob.GetWorkUnit(units[0].ID)
	if !ok {
		t.Fatal("resumed OCR unit was not registered")
	}
	if info.UnitType != WorkUnitTypeOCR || info.PageNum != 2 || info.Provider != "chandra-local" {
		t.Fatalf("resumed work = %#v, want OCR for page 2 via chandra-local", info)
	}
}

// A deterministic page-content failure may still be skipped after retries. It
// is unlikely to recover when replayed, and must not prevent the other pages in
// a large book from completing.
func TestOnCompleteOcrDeterministicFailureAfterRetriesSkipsPageAndContinues(t *testing.T) {
	j, book := newOcrSkipJob()

	const unitID = "wu-ocr-pathological-12"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeOCR,
		PageNum:    12,
		Provider:   "chandra-local",
		RetryCount: MaxOCRPageRetries,
	})

	units, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("OCR failed: invalid image content"),
	})

	if err != nil {
		t.Fatalf("OnComplete returned a fatal error for deterministic page failure; want skip: %v", err)
	}
	if len(units) != 0 {
		t.Fatalf("expected no new work units after skipping the page, got %d", len(units))
	}
	if page := book.GetPage(12); page == nil || !page.OcrComplete("chandra-local") {
		t.Fatal("deterministically failing page should be marked OCR-resolved after retries")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed OCR work unit should be removed after skipping the page")
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
		Error:      fmt.Errorf("OCR failed: invalid image content"),
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
