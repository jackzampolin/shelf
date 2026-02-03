package common

import (
	"context"
	"encoding/base64"
	"fmt"
	"os"
	"strings"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
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
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("CreateOcrWorkUnit: failed to read image",
				"page_num", pageNum,
				"provider", provider,
				"path", imagePath,
				"is_not_exist", os.IsNotExist(err),
				"error", err)
		}
		return nil, ""
	}

	unitID := uuid.New().String()

	return &jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeOCR,
		Provider: provider,
		JobID:    jc.ID(),
		Priority: jobs.PriorityForStage("ocr"),
		OCRRequest: &jobs.OCRWorkRequest{
			Image:   imageData,
			PageNum: pageNum,
		},
		Metrics: &jobs.WorkUnitMetrics{
			BookID:  book.BookID,
			Stage:   "ocr",
			ItemKey: fmt.Sprintf("page_%04d_%s", pageNum, provider),
		},
	}, unitID
}

// PersistOCRResult persists an OCR result to DefraDB and updates the page state (thread-safe).
// Returns (allDone, error) where allDone is true if all OCR providers are now complete for this page.
// Returns error if sink is not available (callers should distinguish failure from incomplete).
func PersistOCRResult(ctx context.Context, book *BookState, state *PageState, ocrProviders []string, provider string, result *providers.OCRResult) (bool, error) {
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

		// Persist header/footer extracted by OCR provider (Mistral)
		if result.Header != "" || result.Footer != "" {
			update := map[string]any{}
			if result.Header != "" {
				update["header"] = result.Header
				state.SetHeader(result.Header)
			}
			if result.Footer != "" {
				update["footer"] = result.Footer
				state.SetFooter(result.Footer)
			}
			if writeResult, err := SendTracked(ctx, book, defra.WriteOp{
				Collection: "Page",
				DocID:      pageDocID,
				Document:   update,
				Op:         defra.OpUpdate,
			}); err == nil {
				if writeResult.CID != "" {
					state.SetPageCID(writeResult.CID)
				}
			} else if logger != nil {
				logger.Warn("failed to persist OCR header/footer",
					"page_doc_id", pageDocID,
					"provider", provider,
					"error", err)
			}
		}

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
		if writeResult, err := SendTracked(ctx, book, defra.WriteOp{
			Collection: "Page",
			DocID:      pageDocID,
			Document:   map[string]any{"ocr_complete": true},
			Op:         defra.OpUpdate,
		}); err == nil {
			if writeResult.CID != "" {
				state.SetPageCID(writeResult.CID)
			}
		} else if logger != nil {
			logger.Warn("failed to persist OCR completion",
				"page_doc_id", pageDocID,
				"error", err)
		}
	}

	return allDone, nil
}

// SaveExtractedImages saves images from OCR metadata to disk and updates the text.
// Returns the updated text with image references pointing to saved files.
// If no images are present or saving fails, returns the original text unchanged.
func SaveExtractedImages(ctx context.Context, homeDir *home.Dir, bookID string, pageNum int, result *providers.OCRResult) string {
	if result == nil || result.Metadata == nil {
		return result.Text
	}

	logger := svcctx.LoggerFrom(ctx)

	// Check for images in metadata (from Mistral OCR)
	imagesRaw, ok := result.Metadata["images"]
	if !ok {
		return result.Text
	}

	images, ok := imagesRaw.([]map[string]any)
	if !ok {
		return result.Text
	}

	if len(images) == 0 {
		return result.Text
	}

	// Ensure directory exists
	if err := homeDir.EnsurePageExtractedImagesDir(bookID, pageNum); err != nil {
		if logger != nil {
			logger.Warn("failed to create extracted images directory",
				"book_id", bookID,
				"page_num", pageNum,
				"error", err)
		}
		return result.Text
	}

	text := result.Text
	savedCount := 0

	for _, img := range images {
		// Get image ID (e.g., "img-0.jpeg")
		imageID, ok := img["id"].(string)
		if !ok || imageID == "" {
			continue
		}

		// Check if base64 data is present
		hasBase64, _ := img["has_base64"].(bool)
		if !hasBase64 {
			continue
		}

		// Get the base64 data from the original response
		// Note: The metadata stores "has_base64" flag, but actual data may be in raw response
		// For now, we'll need to ensure Mistral provider stores the actual base64 data
		base64Data, ok := img["image_base64"].(string)
		if !ok || base64Data == "" {
			continue
		}

		// Decode base64
		imageData, err := base64.StdEncoding.DecodeString(base64Data)
		if err != nil {
			if logger != nil {
				logger.Warn("failed to decode image base64",
					"book_id", bookID,
					"page_num", pageNum,
					"image_id", imageID,
					"error", err)
			}
			continue
		}

		// Save to disk
		imagePath := homeDir.ExtractedImagePath(bookID, pageNum, imageID)
		if err := os.WriteFile(imagePath, imageData, 0o644); err != nil {
			if logger != nil {
				logger.Warn("failed to save extracted image",
					"book_id", bookID,
					"page_num", pageNum,
					"image_id", imageID,
					"path", imagePath,
					"error", err)
			}
			continue
		}

		// Update markdown to reference the saved file path
		// Mistral markdown: ![img-0.jpeg](img-0.jpeg) -> ![img-0.jpeg](/path/to/img-0.jpeg)
		oldRef := fmt.Sprintf("(%s)", imageID)
		newRef := fmt.Sprintf("(%s)", imagePath)
		text = strings.Replace(text, oldRef, newRef, 1)

		savedCount++
		if logger != nil {
			logger.Debug("saved extracted image",
				"book_id", bookID,
				"page_num", pageNum,
				"image_id", imageID,
				"path", imagePath)
		}
	}

	if savedCount > 0 && logger != nil {
		logger.Info("saved extracted images from page",
			"book_id", bookID,
			"page_num", pageNum,
			"count", savedCount)
	}

	return text
}
