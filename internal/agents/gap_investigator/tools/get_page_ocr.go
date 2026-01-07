package tools

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/providers"
)

func getPageOcrTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "get_page_ocr",
			Description: "Get the blended OCR text for a specific page. Use to check if a page has a chapter heading or other structural element.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_num": map[string]any{
						"type":        "integer",
						"description": "Page number to get OCR text for",
					},
				},
				"required": []string{"page_num"},
			}),
		},
	}
}

func (t *GapInvestigatorTools) getPageOcr(ctx context.Context, pageNum int) (string, error) {
	if pageNum < 1 || pageNum > t.totalPages {
		return jsonError(fmt.Sprintf("Invalid page number: %d (book has %d pages)", pageNum, t.totalPages)), nil
	}

	text, err := t.getPageBlendedText(ctx, pageNum)
	if err != nil {
		return jsonError(fmt.Sprintf("No OCR data for page %d: %v", pageNum, err)), nil
	}

	inGap := pageNum >= t.gap.StartPage && pageNum <= t.gap.EndPage

	result := map[string]any{
		"page_num":   pageNum,
		"ocr_text":   text,
		"char_count": len(text),
		"in_gap":     inGap,
	}

	return jsonSuccess(result), nil
}
