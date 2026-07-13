package job

import (
	"context"
	"fmt"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func newMetadataRetryJob() *Job {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	book.EnableMetadata = true
	book.MetadataProvider = "qwen-local"
	book.TotalPages = OcrThresholdForMetadata
	for pageNum := 1; pageNum <= OcrThresholdForMetadata; pageNum++ {
		page := book.GetOrCreatePage(pageNum)
		page.MarkOcrComplete("chandra-local", "OCR text for metadata.")
		page.SetOcrMarkdown("OCR text for metadata.")
	}

	return NewFromLoadResult(&common.LoadBookResult{Book: book})
}

func TestOnCompleteBookOperationFailureRetriesBeforeFailingJob(t *testing.T) {
	j := newMetadataRetryJob()

	const unitID = "wu-metadata-1"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeMetadata,
		RetryCount: 1,
	})

	units, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("request failed: dial tcp: connection refused"),
	})
	if err != nil {
		t.Fatalf("OnComplete returned error before book op retries were exhausted: %v", err)
	}
	if len(units) != 1 {
		t.Fatalf("retry units = %d, want 1", len(units))
	}
	if _, ok := j.GetWorkUnit(unitID); ok {
		t.Fatal("failed metadata work unit should be removed after retry is created")
	}

	info, ok := j.GetWorkUnit(units[0].ID)
	if !ok {
		t.Fatal("new metadata retry work unit should be tracked")
	}
	if info.UnitType != WorkUnitTypeMetadata {
		t.Fatalf("retry unit type = %q, want %q", info.UnitType, WorkUnitTypeMetadata)
	}
	if info.RetryCount != 2 {
		t.Fatalf("retry count = %d, want 2", info.RetryCount)
	}
	state := j.Book.GetMetadataState()
	if !state.IsStarted() || state.Retries() != 2 {
		t.Fatalf("durable metadata state = started:%v retries:%d, want true/2", state.IsStarted(), state.Retries())
	}
	store := j.Book.Store.(*common.MemoryStateStore)
	bookDoc := store.GetDoc("Book", "book-1")
	if bookDoc["metadata_started"] != true || bookDoc["metadata_retries"] != 2 {
		t.Fatalf("persisted metadata retry = %#v", bookDoc)
	}
}

func TestBookOperationCreationRestoresDurableRetryCount(t *testing.T) {
	j := newMetadataRetryJob()
	j.Book.SetOpState(common.OpMetadata, true, false, false, 2)

	unit := j.CreateMetadataWorkUnit(context.Background())
	if unit == nil {
		t.Fatal("metadata work unit = nil")
	}
	info, ok := j.GetWorkUnit(unit.ID)
	if !ok || info.RetryCount != 2 {
		t.Fatalf("restored work unit info = %#v, exists=%v", info, ok)
	}
}

func TestOnCompleteBookOperationFailureAfterRetriesFailsJob(t *testing.T) {
	j := newMetadataRetryJob()

	const unitID = "wu-metadata-1"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeMetadata,
		RetryCount: MaxBookOpRetries,
	})

	_, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("request failed: dial tcp: connection refused"),
	})
	if err == nil {
		t.Fatal("OnComplete error = nil, want fatal error after book op retries are exhausted")
	}
	state := j.Book.GetMetadataState()
	if !state.IsFailed() {
		t.Fatal("metadata operation should be marked failed after retry exhaustion")
	}
}

func TestOnCompleteBookOpFailsFastOnNonRetriableError(t *testing.T) {
	j := newMetadataRetryJob()

	const unitID = "wu-metadata-1"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeMetadata,
		RetryCount: 0,
	})

	_, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("OpenRouter error (status 400): This model's maximum context length is 65536 tokens"),
	})
	if err == nil {
		t.Fatal("OnComplete error = nil, want fatal error (non-retriable 400 should not retry)")
	}
	state := j.Book.GetMetadataState()
	if !state.IsFailed() {
		t.Fatal("metadata should be marked failed on a non-retriable error")
	}
}
