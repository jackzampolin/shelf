package ocr

import (
	"context"
	"fmt"
	"os"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MaxRetries is the maximum number of retries for OCR operations.
const MaxRetries = 10

// OcrWorkUnitParams contains the parameters needed to create an OCR work unit.
type OcrWorkUnitParams struct {
	HomeDir  *home.Dir
	BookID   string
	JobID    string
	PageNum  int
	Provider string
	Stage    string // For metrics (e.g., "ocr" or "process_book")
}

// CreateOcrWorkUnitFunc creates an OCR work unit for a page and provider.
// Returns nil if the image file doesn't exist.
// The registerFn callback is called with the unit ID for tracking.
func CreateOcrWorkUnitFunc(
	params OcrWorkUnitParams,
	registerFn func(unitID string),
) *jobs.WorkUnit {
	imagePath := params.HomeDir.SourceImagePath(params.BookID, params.PageNum)
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		return nil // Skip if image not found
	}

	unitID := uuid.New().String()

	if registerFn != nil {
		registerFn(unitID)
	}

	return &jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeOCR,
		Provider: params.Provider,
		JobID:    params.JobID,
		OCRRequest: &jobs.OCRWorkRequest{
			Image:   imageData,
			PageNum: params.PageNum,
		},
		Metrics: &jobs.WorkUnitMetrics{
			BookID:  params.BookID,
			Stage:   params.Stage,
			ItemKey: fmt.Sprintf("page_%04d_%s", params.PageNum, params.Provider),
		},
	}
}

// HandleOcrResultParams contains parameters for handling OCR completion.
type HandleOcrResultParams struct {
	PageNum   int
	Provider  string
	PageDocID string
	Result    *providers.OCRResult
}

// HandleOcrResultFunc processes an OCR result and updates state.
// Returns true if all providers are now complete for this page.
func HandleOcrResultFunc(
	ctx context.Context,
	params HandleOcrResultParams,
	state *PageState,
	providers []string,
) (allDone bool, err error) {
	if state == nil {
		return false, fmt.Errorf("no state for page %d", params.PageNum)
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return false, fmt.Errorf("defra sink not in context")
	}

	if params.Result != nil {
		// Fire-and-forget write - sink batches these
		sink.Send(defra.WriteOp{
			Collection: "OcrResult",
			Document: map[string]any{
				"page_id":  params.PageDocID,
				"provider": params.Provider,
				"text":     params.Result.Text,
			},
			Op: defra.OpCreate,
		})

		// Update in-memory state immediately
		state.OcrResults[params.Provider] = params.Result.Text
		state.OcrDone[params.Provider] = true
	}

	// Check if all OCR providers are done
	allDone = state.AllOcrDone(providers)

	if allDone {
		// Mark page as OCR complete
		sink.Send(defra.WriteOp{
			Collection: "Page",
			DocID:      params.PageDocID,
			Document:   map[string]any{"ocr_complete": true},
			Op:         defra.OpUpdate,
		})
	}

	return allDone, nil
}

// NeedsOcr checks if a page needs OCR for a specific provider.
func NeedsOcr(state *PageState, provider string) bool {
	if state == nil {
		return true
	}
	return !state.OcrDone[provider]
}

// CountOcrComplete counts how many pages have all OCR providers complete.
func CountOcrComplete(pageState map[int]*PageState, providers []string) int {
	count := 0
	for _, state := range pageState {
		if state.AllOcrDone(providers) {
			count++
		}
	}
	return count
}

// CountProviderComplete counts how many pages have a specific provider complete.
func CountProviderComplete(pageState map[int]*PageState, provider string) int {
	count := 0
	for _, state := range pageState {
		if state.OcrDone[provider] {
			count++
		}
	}
	return count
}
