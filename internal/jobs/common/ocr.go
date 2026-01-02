package common

import (
	"context"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PersistOCRResult persists an OCR result to DefraDB and updates the page state.
// Returns true if all OCR providers are now complete for this page.
func PersistOCRResult(ctx context.Context, state *PageState, ocrProviders []string, provider string, result *providers.OCRResult) bool {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return false
	}

	if result != nil {
		// Fire-and-forget write - sink batches these
		sink.Send(defra.WriteOp{
			Collection: "OcrResult",
			Document: map[string]any{
				"page_id":  state.PageDocID,
				"provider": provider,
				"text":     result.Text,
			},
			Op: defra.OpCreate,
		})

		// Update in-memory state immediately
		state.MarkOcrComplete(provider, result.Text)
	}

	// Check if all OCR providers are done
	allDone := state.AllOcrDone(ocrProviders)

	if allDone {
		// Mark page as OCR complete
		sink.Send(defra.WriteOp{
			Collection: "Page",
			DocID:      state.PageDocID,
			Document:   map[string]any{"ocr_complete": true},
			Op:         defra.OpUpdate,
		})
	}

	return allDone
}
