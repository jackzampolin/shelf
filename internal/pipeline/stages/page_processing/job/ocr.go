package job

import (
	"context"
	"fmt"
	"os"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/jobs"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
func (j *Job) CreateOcrWorkUnit(pageNum int, provider string) *jobs.WorkUnit {
	imagePath := j.HomeDir.SourceImagePath(j.BookID, pageNum)
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		return nil // Skip if image not found
	}

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		PageNum:  pageNum,
		UnitType: "ocr",
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
	}
}

// HandleOcrComplete processes OCR completion.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.PageState[info.PageNum]
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	if result.OCRResult != nil {
		state.OcrResults[info.Provider] = result.OCRResult.Text
		state.OcrDone[info.Provider] = true

		field := fmt.Sprintf("ocr_%s", info.Provider)
		if err := j.DefraClient.Update(ctx, "Page", state.PageDocID, map[string]any{
			field: result.OCRResult.Text,
		}); err != nil {
			return nil, fmt.Errorf("failed to save OCR result: %w", err)
		}
	}

	// Check if all OCR providers are done
	allOcrDone := true
	for _, provider := range j.OcrProviders {
		if !state.OcrDone[provider] {
			allOcrDone = false
			break
		}
	}

	var units []jobs.WorkUnit
	if allOcrDone {
		if err := j.DefraClient.Update(ctx, "Page", state.PageDocID, map[string]any{
			"ocr_complete": true,
		}); err != nil {
			return nil, fmt.Errorf("failed to mark OCR complete: %w", err)
		}

		blendUnit := j.CreateBlendWorkUnit(info.PageNum, state)
		if blendUnit != nil {
			units = append(units, *blendUnit)
		}
	}

	return units, nil
}
