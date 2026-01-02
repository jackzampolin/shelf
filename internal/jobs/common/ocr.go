package common

import (
	"context"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PersistOCRResult persists an OCR result to DefraDB and updates the page state (thread-safe).
// Returns true if all OCR providers are now complete for this page.
func PersistOCRResult(ctx context.Context, state *PageState, ocrProviders []string, provider string, result *providers.OCRResult) bool {
	logger := svcctx.LoggerFrom(ctx)
	pageDocID := state.GetPageDocID()

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		if logger != nil {
			logger.Warn("defra sink not in context, OCR result will not be persisted",
				"page_doc_id", pageDocID,
				"provider", provider)
		}
		return false
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

	return allDone
}
