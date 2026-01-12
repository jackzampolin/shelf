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
			Description: "Load a SINGLE page image to see it visually. WORKFLOW: Document what you see in the CURRENT page, THEN specify which page to load next. One page at a time - when you load a new page, the previous page is automatically removed from context. This forces you to record findings before moving on. First call doesn't need observations (nothing loaded yet).",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_num": map[string]any{
						"type":        "integer",
						"description": "Page number to load NEXT (e.g., 6)",
					},
					"current_page_observations": map[string]any{
						"type":        "string",
						"description": "What do you see on the page that's CURRENTLY loaded in context? REQUIRED if a page is already in context. Document: Is it ToC? Part of ToC? Not ToC? What visual markers? Be specific about what you SEE right now before swapping to the next page.",
					},
				},
				"required": []string{"page_num"},
			}),
		},
	}
}

func (t *ToCFinderTools) loadPageImage(ctx context.Context, pageNum int, currentPageObservations string) (string, error) {
	// If we already have a page loaded, require observations
	if t.currentPageNum != nil {
		if currentPageObservations == "" {
			return jsonError(fmt.Sprintf(
				"You are currently viewing page %d. You must provide 'current_page_observations' documenting what you SEE on this page before loading page %d.",
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
			fmt.Sprintf("Page %d observations recorded and removed from context.", *previousPage))
	}

	return jsonSuccess(map[string]any{
		"current_page":       pageNum,
		"previous_page":      previousPage,
		"observations_count": len(t.pageObservations),
		"message":            strings.Join(messageParts, " "),
	}), nil
}
