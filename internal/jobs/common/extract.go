package common

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateExtractWorkUnit creates a CPU work unit to extract a page from PDF.
// Returns nil if the page is out of range.
// The caller is responsible for registering the work unit with their tracker.
func CreateExtractWorkUnit(jc JobContext, pageNum int) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	pdfPath, pageInPDF := book.PDFs.FindPDFForPage(pageNum)
	if pdfPath == "" {
		return nil, ""
	}

	unitID := uuid.New().String()

	return &jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeCPU,
		JobID:    jc.ID(),
		Priority: jobs.PriorityForStage("extract"),
		CPURequest: &jobs.CPUWorkRequest{
			Task: ingest.TaskExtractPage,
			Data: ingest.PageExtractRequest{
				PDFPath:   pdfPath,
				PageNum:   pageInPDF,
				OutputNum: pageNum,
				OutputDir: book.HomeDir.SourceImagesDir(book.BookID),
			},
		},
	}, unitID
}

// PersistExtractState saves extraction completion to DefraDB asynchronously.
// The in-memory state is already updated; DB persistence is fire-and-forget.
// Returns error if pageDocID is empty or sink is not in context.
func PersistExtractState(ctx context.Context, book *BookState, pageDocID string) (string, error) {
	if pageDocID == "" {
		return "", fmt.Errorf("cannot persist extract state: empty page document ID")
	}
	// Use async send - extract state is not on the critical path
	// In-memory state tracks completion; DB is just for persistence/recovery
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return "", fmt.Errorf("defra sink not in context")
	}
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      pageDocID,
		Document:   map[string]any{"extract_complete": true},
		Op:         defra.OpUpdate,
		Source:     "PersistExtractState",
	})
	return "", nil // CID not available for async writes
}
