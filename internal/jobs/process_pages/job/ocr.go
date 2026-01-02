package job

import (
	"context"
	"fmt"
	"os"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
// Returns nil if the image file doesn't exist (expected case - needs extraction first).
func (j *Job) CreateOcrWorkUnit(ctx context.Context, pageNum int, provider string) *jobs.WorkUnit {
	imagePath := j.Book.HomeDir.SourceImagePath(j.Book.BookID, pageNum)
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		if os.IsNotExist(err) {
			return nil // Expected: image needs extraction first
		}
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to read image for OCR",
				"page_num", pageNum,
				"provider", provider,
				"error", err)
		}
		return nil
	}

	unitID := uuid.New().String()

	// Register for tracking
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		PageNum:  pageNum,
		UnitType: WorkUnitTypeOCR,
		Provider: provider,
	})

	return &jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeOCR,
		Provider: provider,
		JobID:    j.RecordID,
		OCRRequest: &jobs.OCRWorkRequest{
			Image:   imageData,
			PageNum: pageNum,
		},
		Metrics: &jobs.WorkUnitMetrics{
			BookID:  j.Book.BookID,
			Stage:   j.Type(),
			ItemKey: fmt.Sprintf("page_%04d_%s", pageNum, provider),
		},
	}
}

// HandleOcrComplete processes OCR completion.
// Updates state, persists to DefraDB, and triggers blend if all OCR done.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	// Use common handler for persistence and state update
	allDone := common.PersistOCRResult(ctx, state, j.Book.OcrProviders, info.Provider, result.OCRResult)

	// If all OCR done, trigger blend
	var units []jobs.WorkUnit
	if allDone {
		blendUnit := j.CreateBlendWorkUnit(info.PageNum, state)
		if blendUnit != nil {
			units = append(units, *blendUnit)
		}
	}

	return units, nil
}
