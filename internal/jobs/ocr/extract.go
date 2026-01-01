package ocr

import (
	"context"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// CreateExtractWorkUnit creates a CPU work unit to extract a page from PDF.
func (j *Job) CreateExtractWorkUnit(pageNum int) *jobs.WorkUnit {
	pdfPath, pageInPDF := j.PDFs.FindPDFForPage(pageNum)
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
	return j.GenerateOcrWorkUnitsForPage(pageNum), nil
}

// PersistExtractState saves extraction completion to DefraDB.
func (j *Job) PersistExtractState(ctx context.Context, pageNum int) {
	state := j.PageState[pageNum]
	if state == nil {
		return
	}
	common.PersistExtractState(ctx, state.PageDocID)
}

// GenerateOcrWorkUnitsForPage creates OCR work units for a single page.
func (j *Job) GenerateOcrWorkUnitsForPage(pageNum int) []jobs.WorkUnit {
	var units []jobs.WorkUnit
	state := j.PageState[pageNum]
	if state == nil {
		return units
	}

	for _, provider := range j.OcrProviders {
		if !state.OcrDone[provider] {
			unit := j.CreateOcrWorkUnit(pageNum, provider)
			if unit != nil {
				units = append(units, *unit)
			}
		}
	}
	return units
}

// NeedsExtraction checks if a page needs extraction (image doesn't exist).
func (j *Job) NeedsExtraction(pageNum int) bool {
	state := j.PageState[pageNum]
	extractDone := state != nil && state.ExtractDone
	return common.NeedsExtraction(j.HomeDir, j.BookID, pageNum, extractDone)
}
