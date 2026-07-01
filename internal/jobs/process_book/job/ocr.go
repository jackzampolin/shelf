package job

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
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

// skipFailedOcrPage records a page whose OCR exhausted its retries as resolved
// with no text. A single pathological or persistently-failing page must not kill
// the whole book; treating it like a blank page lets the remaining pages and the
// downstream stages proceed.
//
// The skip is persisted like a blank page (an empty OcrResult row + ocr_complete)
// so a server restart does not re-grind the page: LoadBook reads that row on
// resume and treats the provider as done. When no sink is available (tests) or
// persistence fails, fall back to the in-memory mark so the book still proceeds.
func (j *Job) skipFailedOcrPage(ctx context.Context, info WorkUnitInfo, cause error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return
	}

	persisted := false
	if svcctx.DefraSinkFrom(ctx) != nil {
		if _, err := common.PersistOCRResult(ctx, j.Book, state, j.Book.OcrProviders, info.Provider, &providers.OCRResult{}); err != nil {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("failed to persist skipped OCR page; continuing with in-memory mark",
					"book_id", j.Book.BookID,
					"page_num", info.PageNum,
					"error", err)
			}
		} else {
			persisted = true
		}
	}
	if !persisted {
		state.MarkOcrComplete(info.Provider, "")
	}

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Warn("OCR failed after retries; skipping page to keep the book processing",
			"book_id", j.Book.BookID,
			"page_num", info.PageNum,
			"provider", info.Provider,
			"retry_count", info.RetryCount,
			"persisted", persisted,
			"error", cause)
	}
}

// skipFailedExtractPage abandons a page whose image extraction exhausted its
// retries. Without an image the page cannot be OCR'd, so it is resolved as a
// blank page (extract-done + OCR resolved with no text) rather than failing the
// whole book — with thousands of pages, corrupt/pathological PDF pages are
// common. extract_complete is persisted best-effort and OCR is resolved per
// provider (which persists too) so a restart does not re-grind the page.
func (j *Job) skipFailedExtractPage(ctx context.Context, info WorkUnitInfo, cause error) {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return
	}
	state.SetExtractDone(true)
	if sink := svcctx.DefraSinkFrom(ctx); sink != nil {
		if docID := state.GetPageDocID(); docID != "" {
			sink.Send(defra.WriteOp{
				Collection: "Page",
				DocID:      docID,
				Document:   map[string]any{"extract_complete": true},
				Op:         defra.OpUpdate,
				Source:     "skipFailedExtractPage",
			})
		}
	}
	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Warn("extract failed after retries; skipping page to keep the book processing",
			"book_id", j.Book.BookID,
			"page_num", info.PageNum,
			"retry_count", info.RetryCount,
			"error", cause)
	}
	// No image means no OCR is possible; resolve OCR as empty for every provider so
	// the OCR stage can complete and downstream stages run.
	for _, provider := range j.Book.OcrProviders {
		j.skipFailedOcrPage(ctx, WorkUnitInfo{PageNum: info.PageNum, Provider: provider, RetryCount: info.RetryCount}, cause)
	}
}

// HandleOcrComplete processes OCR completion.
// Updates state, persists to DefraDB, and when all OCR is done, stores ocr_markdown
// directly and triggers book-level operations.
func (j *Job) HandleOcrComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		hasOCRResult := result.OCRResult != nil
		ocrText := ""
		if hasOCRResult {
			ocrText = fmt.Sprintf("%d chars", len(result.OCRResult.Text))
		}
		logger.Debug("received OCR completion result",
			"page_num", info.PageNum,
			"provider", info.Provider,
			"success", result.Success,
			"has_ocr_result", hasOCRResult,
			"ocr_text", ocrText,
			"error", result.Error)
	}

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
	allDone, err := common.PersistOCRResult(ctx, j.Book, state, j.Book.OcrProviders, info.Provider, result.OCRResult)
	if err != nil {
		if logger != nil {
			logger.Error("persisting OCR result failed",
				"page_num", info.PageNum,
				"provider", info.Provider,
				"error", err)
		}
		return nil, fmt.Errorf("failed to persist OCR result for page %d provider %s: %w", info.PageNum, info.Provider, err)
	}
	if logger != nil {
		logger.Debug("persisted OCR result",
			"page_num", info.PageNum,
			"provider", info.Provider,
			"all_done", allDone)
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

		// Persist ocr_markdown and headings to page state and DefraDB (async)
		if ocrText != "" {
			headings := common.ExtractHeadings(ocrText)
			state.SetOcrMarkdownWithHeadings(ocrText, headings)

			pageDocID := state.GetPageDocID()
			update := map[string]any{"ocr_markdown": ocrText}
			if headingsJSON, err := json.Marshal(headings); err == nil {
				update["headings"] = string(headingsJSON)
			} else if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("failed to marshal headings", "page_num", info.PageNum, "error", err)
			}
			// Use async send - in-memory state already has the data
			sink := svcctx.DefraSinkFrom(ctx)
			if sink != nil {
				sink.Send(defra.WriteOp{
					Collection: "Page",
					DocID:      pageDocID,
					Document:   update,
					Op:         defra.OpUpdate,
					Source:     "HandleOcrComplete:markdown",
				})
			}
		}

		// Check if any book operations should start now
		units = append(units, j.MaybeStartBookOperations(ctx)...)
	}

	return units, nil
}
