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
			Description: "Get the blended OCR text for a specific page. Use this to verify that a candidate page actually contains the chapter heading at the top. Check for: heading at top of page, chapter number format matches, body text follows.",
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

func (t *ChapterFinderTools) getPageOcr(ctx context.Context, pageNum int) (string, error) {
	if pageNum < 1 || pageNum > t.totalPages {
		return jsonError(fmt.Sprintf("Invalid page number: %d (book has %d pages)", pageNum, t.totalPages)), nil
	}

	text, err := t.getPageBlendedText(ctx, pageNum)
	if err != nil {
		return jsonError(fmt.Sprintf("No OCR data for page %d: %v", pageNum, err)), nil
	}

	// Check if in excluded range
	inExcluded := t.isInExcludedRange(pageNum)

	result := map[string]any{
		"page_num":          pageNum,
		"ocr_text":          text,
		"char_count":        len(text),
		"in_excluded_range": inExcluded,
	}

	if inExcluded {
		result["warning"] = "This page is in an EXCLUDED range (back matter). This is likely not the chapter start - probably a footnote/endnote reference."
	}

	return jsonSuccess(result), nil
}
