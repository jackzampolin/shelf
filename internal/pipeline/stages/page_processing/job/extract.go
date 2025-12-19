package job

import (
	"context"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateExtractWorkUnit creates a CPU work unit to extract a page from PDF.
func (j *Job) CreateExtractWorkUnit(pageNum int) *jobs.WorkUnit {
	pdfPath, pageInPDF := j.FindPDFForPage(pageNum)
	if pdfPath == "" {
		return nil // Page out of range
	}

	unitID := uuid.New().String()

	// Register for tracking
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		PageNum:  pageNum,
		UnitType: "extract",
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
				OutputDir: j.HomeDir.SourceImagesDir(j.BookID),
			},
		},
	}
}

// HandleExtractComplete processes the result of a page extraction.
func (j *Job) HandleExtractComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	pageNum := info.PageNum
	state := j.PageState[pageNum]
	if state == nil {
		// This shouldn't happen, but be safe
		state = NewPageState()
		j.PageState[pageNum] = state
	}

	// Mark extraction done
	state.ExtractDone = true

	// Persist to DefraDB
	j.PersistExtractState(ctx, pageNum)

	// Generate OCR work units now that image is on disk
	return j.GeneratePageWorkUnits(ctx, pageNum, state), nil
}

// PersistExtractState saves extraction completion to DefraDB.
func (j *Job) PersistExtractState(ctx context.Context, pageNum int) {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return
	}

	state := j.PageState[pageNum]
	if state == nil || state.PageDocID == "" {
		return
	}

	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.PageDocID,
		Document:   map[string]any{"extract_complete": true},
		Op:         defra.OpUpdate,
	})
}
