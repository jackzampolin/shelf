package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// CreateExtractWorkUnit creates a CPU work unit to extract a page from PDF.
func (j *Job) CreateExtractWorkUnit(pageNum int) *jobs.WorkUnit {
	pdfPath, pageInPDF := j.Book.PDFs.FindPDFForPage(pageNum)
	if pdfPath == "" {
		return nil // Page out of range
	}

	unitID := uuid.New().String()

	// Register for tracking
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		PageNum:  pageNum,
		UnitType: WorkUnitTypeExtract,
	})

	return &jobs.WorkUnit{
		ID:    unitID,
		Type:  jobs.WorkUnitTypeCPU,
		JobID: j.RecordID,
		CPURequest: &jobs.CPUWorkRequest{
			Task: ingest.TaskExtractPage,
			Data: ingest.PageExtractRequest{
				PDFPath:   pdfPath,
				PageNum:   pageInPDF,         // Page number within the PDF
				OutputNum: pageNum,           // Sequential output page number
				OutputDir: j.Book.HomeDir.SourceImagesDir(j.Book.BookID),
			},
		},
	}
}

// HandleExtractComplete processes the result of a page extraction.
func (j *Job) HandleExtractComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	pageNum := info.PageNum
	state := j.Book.GetOrCreatePage(pageNum)

	// Mark extraction done (thread-safe)
	state.SetExtractDone(true)

	// Persist to DefraDB using common function (thread-safe accessor)
	if err := common.PersistExtractState(ctx, state.GetPageDocID()); err != nil {
		return nil, fmt.Errorf("failed to persist extract state for page %d: %w", pageNum, err)
	}

	// Generate OCR work units now that image is on disk
	return j.GeneratePageWorkUnits(ctx, pageNum, state), nil
}
