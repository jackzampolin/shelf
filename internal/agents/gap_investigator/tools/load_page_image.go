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
			Description: "Load a page image for visual inspection. Use to verify chapter headings, especially when OCR might have errors.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_num": map[string]any{
						"type":        "integer",
						"description": "Page number to load",
					},
					"current_page_observations": map[string]any{
						"type":        "string",
						"description": "What did you see on the currently loaded page? Required if a page is already loaded.",
					},
				},
				"required": []string{"page_num"},
			}),
		},
	}
}

func (t *GapInvestigatorTools) loadPageImage(ctx context.Context, pageNum int, currentPageObservations string) (string, error) {
	if pageNum < 1 || pageNum > t.book.TotalPages {
		return jsonError(fmt.Sprintf("Invalid page number: %d (book has %d pages)", pageNum, t.book.TotalPages)), nil
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
	imagePath := t.book.HomeDir.SourceImagePath(t.book.BookID, pageNum)
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
			fmt.Sprintf("Page %d observations recorded.", *previousPage))
	}

	inGap := pageNum >= t.gap.StartPage && pageNum <= t.gap.EndPage
	if inGap {
		messageParts = append(messageParts, "This page is WITHIN the gap.")
	}

	return jsonSuccess(map[string]any{
		"current_page":       pageNum,
		"previous_page":      previousPage,
		"in_gap":             inGap,
		"observations_count": len(t.pageObservations),
		"message":            strings.Join(messageParts, " "),
	}), nil
}
