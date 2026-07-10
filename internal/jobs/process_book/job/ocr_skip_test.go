package job

import (
	"context"
	"fmt"
	"os"
	"strings"
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

func TestOcrProviderRetryBudgetIsNotRepeatedByWorkflow(t *testing.T) {
	if MaxOCRPageRetries != 0 {
		t.Fatalf("MaxOCRPageRetries = %d, want zero workflow retries", MaxOCRPageRetries)
	}
	j, _ := newOcrSkipJob()
	const unitID = "wu-ocr-single-budget"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: WorkUnitTypeOCR,
		PageNum:  12,
		Provider: "chandra-local",
	})

	units, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("max retries (3) exceeded: context deadline exceeded"),
	})
	if err == nil {
		t.Fatal("provider budget exhaustion should fail visibly")
	}
	if len(units) != 0 {
		t.Fatalf("provider budget was repeated with %d workflow unit(s)", len(units))
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

// A deterministic page-content failure is actionable, not a blank page. It
// must fail visibly and remain incomplete for targeted repair.
func TestOnCompleteOcrDeterministicFailureAfterRetriesFailsWithoutResolvingPage(t *testing.T) {
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

	if err == nil {
		t.Fatal("OnComplete error = nil, want deterministic page failure to fail visibly")
	}
	if len(units) != 0 {
		t.Fatalf("expected no new work units after fatal page failure, got %d", len(units))
	}
	if page := book.GetPage(12); page == nil || page.OcrComplete("chandra-local") {
		t.Fatal("deterministically failing page must remain incomplete after retries")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed OCR work unit should be removed after failing the job")
	}
	if !strings.Contains(err.Error(), "page=12") || !strings.Contains(err.Error(), "provider=chandra-local") {
		t.Fatalf("error is not actionable: %v", err)
	}
}

// Extraction failure leaves the page unresolved. Treating a corrupt PDF page
// as an extracted blank page would allow a silently degraded complete book.
func TestOnCompleteExtractFailureAfterRetriesFailsWithoutResolvingPage(t *testing.T) {
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
	if err == nil {
		t.Fatal("OnComplete error = nil, want exhausted extraction failure to fail visibly")
	}

	page := book.GetPage(5)
	if page == nil || page.IsExtractDone() {
		t.Fatal("page 5 must remain extraction-incomplete so a repair can re-emit it")
	}
	if page.OcrComplete("chandra-local") {
		t.Fatal("page 5 must remain OCR-incomplete when no image was extracted")
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed extract work unit should be removed after failing the job")
	}
}

// A failed page must not trigger downstream book operations. The pipeline stops
// at the fidelity boundary until that page is repaired.
func TestOnCompleteOcrFailureDoesNotTriggerDownstreamBookOperations(t *testing.T) {
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
	if err == nil {
		t.Fatal("OnComplete error = nil, want failed page to stop downstream work")
	}

	if j.Book.MetadataIsStarted() {
		t.Fatal("failed OCR page must not trigger downstream metadata")
	}
	if len(units) != 0 {
		t.Fatalf("failed OCR page returned %d downstream units, want 0", len(units))
	}
}
