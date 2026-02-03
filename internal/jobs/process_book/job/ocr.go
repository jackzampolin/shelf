package job

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
// Returns nil if the image file doesn't exist (expected case - needs extraction first).
func (j *Job) CreateOcrWorkUnit(ctx context.Context, pageNum int, provider string) *jobs.WorkUnit {
	unit, unitID := common.CreateOcrWorkUnit(ctx, j, pageNum, provider)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			PageNum:  pageNum,
			UnitType: WorkUnitTypeOCR,
			Provider: provider,
		})
	}
	return unit
}

// HandleOcrComplete processes OCR completion.
// Updates state, persists to DefraDB, and when all OCR is done, stores ocr_markdown
// directly and triggers book-level operations.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil, fmt.Errorf("no state for page %d", info.PageNum)
	}

	// Save any extracted images from OCR metadata and update text with file paths
	if result.OCRResult != nil && j.Book.HomeDir != nil {
		updatedText := common.SaveExtractedImages(ctx, j.Book.HomeDir, j.Book.BookID, info.PageNum, result.OCRResult)
		if updatedText != result.OCRResult.Text {
			result.OCRResult.Text = updatedText
		}
	}

	// Use common handler for persistence and state update
	allDone, err := common.PersistOCRResult(ctx, state, j.Book.OcrProviders, info.Provider, result.OCRResult)
	if err != nil {
		return nil, fmt.Errorf("failed to persist OCR result for page %d provider %s: %w", info.PageNum, info.Provider, err)
	}

	// If all OCR done, store the text directly as ocr_markdown and trigger book operations
	var units []jobs.WorkUnit
	if allDone {
		// Use the first provider's OCR text as the ocr_markdown
		ocrText := ""
		for _, provider := range j.Book.OcrProviders {
			if text, ok := state.GetOcrResult(provider); ok && text != "" {
				ocrText = text
				break
			}
		}

		// Persist ocr_markdown and headings to page state and DefraDB
		if ocrText != "" {
			headings := common.ExtractHeadings(ocrText)
			state.SetOcrMarkdownWithHeadings(ocrText, headings)

			sink := svcctx.DefraSinkFrom(ctx)
			if sink != nil {
				pageDocID := state.GetPageDocID()
				update := map[string]any{"ocr_markdown": ocrText}
				if headingsJSON, err := json.Marshal(headings); err == nil {
					update["headings"] = string(headingsJSON)
				} else if logger := svcctx.LoggerFrom(ctx); logger != nil {
					logger.Warn("failed to marshal headings", "page_num", info.PageNum, "error", err)
				}
				if writeResult, err := sink.SendSync(ctx, defra.WriteOp{
					Collection: "Page",
					DocID:      pageDocID,
					Document:   update,
					Op:         defra.OpUpdate,
				}); err == nil {
					if writeResult.CID != "" {
						state.SetPageCID(writeResult.CID)
					}
				}
			}
		}

		// Check if any book operations should start now
		units = append(units, j.MaybeStartBookOperations(ctx)...)
	}

	return units, nil
}
