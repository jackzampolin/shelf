package ocr

import (
	"context"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// createExtractWorkUnit creates a CPU work unit to extract a page from PDF.
func (j *Job) createExtractWorkUnit(pageNum int) *jobs.WorkUnit {
	pdfPath, pageInPDF := j.PDFs.FindPDFForPage(pageNum)
	if pdfPath == "" {
		return nil // Page out of range
	}

	unitID := uuid.New().String()

	// Register for tracking
	j.registerWorkUnit(unitID, WorkUnitInfo{
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
				OutputDir: j.HomeDir.SourceImagesDir(j.BookID),
			},
		},
	}
}

// handleExtractComplete processes the result of a page extraction.
func (j *Job) handleExtractComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	pageNum := info.PageNum
	state := j.pageState[pageNum]
	if state == nil {
		// This shouldn't happen, but be safe
		state = NewPageState()
		j.pageState[pageNum] = state
	}

	// Mark extraction done
	state.ExtractDone = true

	// Persist to DefraDB
	j.persistExtractState(ctx, pageNum)

	// Generate OCR work units now that image is on disk
	return j.generateOcrWorkUnitsForPage(ctx, pageNum), nil
}

// persistExtractState saves extraction completion to DefraDB.
func (j *Job) persistExtractState(ctx context.Context, pageNum int) {
	state := j.pageState[pageNum]
	if state == nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("persistExtractState: no state for page",
				"page_num", pageNum,
				"book_id", j.BookID)
		}
		return
	}
	common.PersistExtractState(ctx, state.PageDocID)
}

// generateOcrWorkUnitsForPage creates OCR work units for a single page.
func (j *Job) generateOcrWorkUnitsForPage(ctx context.Context, pageNum int) []jobs.WorkUnit {
	var units []jobs.WorkUnit
	state := j.pageState[pageNum]
	if state == nil {
		return units
	}

	for _, provider := range j.OcrProviders {
		if !state.OcrComplete(provider) {
			unit := j.createOcrWorkUnit(ctx, pageNum, provider)
			if unit != nil {
				units = append(units, *unit)
			}
		}
	}
	return units
}

// needsExtraction checks if a page needs extraction (image doesn't exist).
func (j *Job) needsExtraction(pageNum int) bool {
	state := j.pageState[pageNum]
	extractDone := state != nil && state.ExtractDone
	return common.NeedsExtraction(j.HomeDir, j.BookID, pageNum, extractDone)
}
