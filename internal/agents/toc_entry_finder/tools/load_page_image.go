package tools

import (
	"context"
	"fmt"
	"os"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

func loadPageImageTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "load_page_image",
			Description: "Load a page image to see it visually. Use for visual verification when OCR is garbled (especially Roman numerals) or when multiple candidates look similar. WORKFLOW: Document what you see on the current page before loading the next one.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_num": map[string]any{
						"type":        "integer",
						"description": "Page number to load",
					},
					"current_page_observations": map[string]any{
						"type":        "string",
						"description": "What did you see on the currently loaded page? Required if a page is already loaded. Document: Is this the chapter start? What visual markers do you see?",
					},
				},
				"required": []string{"page_num"},
			}),
		},
	}
}

func (t *TocEntryFinderTools) loadPageImage(ctx context.Context, pageNum int, currentPageObservations string) (string, error) {
	if pageNum < 1 || pageNum > t.totalPages {
		return jsonError(fmt.Sprintf("Invalid page number: %d (book has %d pages)", pageNum, t.totalPages)), nil
	}

	// If we already have a page loaded, require observations
	if t.currentPageNum != nil {
		if currentPageObservations == "" {
			return jsonError(fmt.Sprintf(
				"You are currently viewing page %d. You must provide 'current_page_observations' documenting what you see before loading page %d.",
				*t.currentPageNum, pageNum,
			)), nil
		}

		// Record observations
		t.pageObservations = append(t.pageObservations, PageObservation{
			PageNum:      *t.currentPageNum,
			Observations: currentPageObservations,
		})
	}

	// Load image file
	imagePath := t.homeDir.SourceImagePath(t.bookID, pageNum)
	imageData, err := os.ReadFile(imagePath)
	if err != nil {
		return jsonError(fmt.Sprintf("Failed to load page image: %v", err)), nil
	}

	// Update state
	previousPage := t.currentPageNum
	t.currentPageNum = &pageNum
	t.currentImages = [][]byte{imageData}

	messageParts := []string{fmt.Sprintf("Now viewing page %d.", pageNum)}
	if previousPage != nil {
		messageParts = append(messageParts,
			fmt.Sprintf("Page %d observations recorded and removed from context.", *previousPage))
	}

	// Check if in back matter
	backMatterStart := int(float64(t.totalPages) * 0.8)
	if pageNum >= backMatterStart {
		messageParts = append(messageParts,
			fmt.Sprintf("⚠️ This page is in the back matter region (page %d+).", backMatterStart))
	}

	return jsonSuccess(map[string]any{
		"current_page":       pageNum,
		"previous_page":      previousPage,
		"observations_count": len(t.pageObservations),
		"message":            strings.Join(messageParts, " "),
	}), nil
}
