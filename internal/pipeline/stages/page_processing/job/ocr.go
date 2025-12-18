package job

import (
	"context"
	"fmt"
	"os"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
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

	metrics := j.MetricsFor()
	metrics.ItemKey = fmt.Sprintf("page_%04d_%s", pageNum, provider)

	return &jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeOCR,
		Provider: provider,
		JobID:    j.RecordID,
		OCRRequest: &jobs.OCRWorkRequest{
			Image:   imageData,
			PageNum: pageNum,
		},
		Metrics: metrics,
	}
}

// HandleOcrComplete processes OCR completion.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.PageState[info.PageNum]
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return nil, fmt.Errorf("defra sink not in context")
	}

	if result.OCRResult != nil {
		// Persist to DefraDB first, then update memory (crash-safe ordering)
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "OcrResult",
			Document: map[string]any{
				"page_id":  state.PageDocID,
				"provider": info.Provider,
				"text":     result.OCRResult.Text,
			},
			Op: defra.OpCreate,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to save OCR result: %w", err)
		}

		// Update in-memory state after successful persistence
		state.OcrResults[info.Provider] = result.OCRResult.Text
		state.OcrDone[info.Provider] = true
	}

	// Check if all OCR providers are done
	allOcrDone := true
	for _, provider := range j.OcrProviders {
		if !state.OcrDone[provider] {
			allOcrDone = false
			break
		}
	}

	// If all OCR done, mark complete and trigger blend
	var units []jobs.WorkUnit
	if allOcrDone {
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "Page",
			DocID:      state.PageDocID,
			Document: map[string]any{
				"ocr_complete": true,
			},
			Op: defra.OpUpdate,
		})
		if err != nil {
			return nil, fmt.Errorf("failed to mark OCR complete: %w", err)
		}

		blendUnit := j.CreateBlendWorkUnit(info.PageNum, state)
		if blendUnit != nil {
			units = append(units, *blendUnit)
		}
	}

	return units, nil
}
