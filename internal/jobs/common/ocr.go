package common

import (
	"context"
	"fmt"
	"os"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateOcrWorkUnit creates an OCR work unit for a page and provider.
// Returns nil if the image file doesn't exist.
// The caller is responsible for registering the work unit with their tracker.
func CreateOcrWorkUnit(ctx context.Context, jc JobContext, pageNum int, provider string) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	imagePath := book.HomeDir.SourceImagePath(book.BookID, pageNum)
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		if !os.IsNotExist(err) {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("failed to read image for OCR",
					"page_num", pageNum,
					"provider", provider,
					"error", err)
			}
		}
		return nil, ""
	}

	unitID := uuid.New().String()

	return &jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeOCR,
		Provider: provider,
		JobID:    jc.ID(),
		OCRRequest: &jobs.OCRWorkRequest{
			Image:   imageData,
			PageNum: pageNum,
		},
		Metrics: &jobs.WorkUnitMetrics{
			BookID:  book.BookID,
			Stage:   jc.Type(),
			ItemKey: fmt.Sprintf("page_%04d_%s", pageNum, provider),
		},
	}, unitID
}

// PersistOCRResult persists an OCR result to DefraDB and updates the page state (thread-safe).
// Returns (allDone, error) where allDone is true if all OCR providers are now complete for this page.
// Returns error if sink is not available (callers should distinguish failure from incomplete).
func PersistOCRResult(ctx context.Context, state *PageState, ocrProviders []string, provider string, result *providers.OCRResult) (bool, error) {
	logger := svcctx.LoggerFrom(ctx)
	pageDocID := state.GetPageDocID()

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return false, fmt.Errorf("defra sink not in context, OCR result will not be persisted for page %s provider %s", pageDocID, provider)
	}

	if result != nil {
		// Fire-and-forget write - sink batches and logs errors internally
		sink.Send(defra.WriteOp{
			Collection: "OcrResult",
			Document: map[string]any{
				"page_id":  pageDocID,
				"provider": provider,
				"text":     result.Text,
			},
			Op: defra.OpCreate,
		})

		// Update in-memory state (thread-safe)
		state.MarkOcrComplete(provider, result.Text)
	} else if logger != nil {
		// Log when result is nil - could indicate blank page or provider error
		logger.Debug("OCR result is nil, not persisting",
			"page_doc_id", pageDocID,
			"provider", provider)
	}

	// Check if all OCR providers are done (thread-safe)
	allDone := state.AllOcrDone(ocrProviders)

	if allDone {
		// Mark page as OCR complete
		sink.Send(defra.WriteOp{
			Collection: "Page",
			DocID:      pageDocID,
			Document:   map[string]any{"ocr_complete": true},
			Op:         defra.OpUpdate,
		})
	}

	return allDone, nil
}
