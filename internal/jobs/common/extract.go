package common

import (
	"context"
	"os"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ExtractWorkUnitInfo contains info needed to create/handle extract work units.
type ExtractWorkUnitInfo struct {
	PageNum    int
	RetryCount int
}

// CreateExtractWorkUnit creates a CPU work unit to extract a page from PDF.
func CreateExtractWorkUnit(
	pdfs PDFList,
	homeDir *home.Dir,
	bookID string,
	jobID string,
	pageNum int,
	retryCount int,
	registerFn func(unitID string, info ExtractWorkUnitInfo),
) *jobs.WorkUnit {
	pdfPath, pageInPDF := pdfs.FindPDFForPage(pageNum)
	if pdfPath == "" {
		return nil // Page out of range
	}

	unitID := uuid.New().String()

	// Register for tracking
	if registerFn != nil {
		registerFn(unitID, ExtractWorkUnitInfo{
			PageNum:    pageNum,
			RetryCount: retryCount,
		})
	}

	return &jobs.WorkUnit{
		ID:    unitID,
		Type:  jobs.WorkUnitTypeCPU,
		JobID: jobID,
		CPURequest: &jobs.CPUWorkRequest{
			Task: ingest.TaskExtractPage,
			Data: ingest.PageExtractRequest{
				PDFPath:   pdfPath,
				PageNum:   pageInPDF,         // Page number within the PDF
				OutputNum: pageNum,           // Sequential output page number
				OutputDir: homeDir.SourceImagesDir(bookID),
			},
		},
	}
}

// PersistExtractState saves extraction completion to DefraDB.
func PersistExtractState(ctx context.Context, pageDocID string) {
	if pageDocID == "" {
		return
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return
	}

	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      pageDocID,
		Document:   map[string]any{"extract_complete": true},
		Op:         defra.OpUpdate,
	})
}

// NeedsExtraction checks if a page needs extraction (image doesn't exist).
func NeedsExtraction(homeDir *home.Dir, bookID string, pageNum int, extractDone bool) bool {
	if extractDone {
		return false
	}

	// Check if image file exists
	imagePath := homeDir.SourceImagePath(bookID, pageNum)
	_, err := os.Stat(imagePath)
	return os.IsNotExist(err)
}
