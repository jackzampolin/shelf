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
			Description: "Get the blended OCR text for a specific page. Use this to verify that a candidate page actually contains the chapter heading (not just a text mention or footnote reference). Check for: heading at top of page, chapter number/title format, body text follows (not citations).",
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

func (t *TocEntryFinderTools) getPageOcr(ctx context.Context, pageNum int) (string, error) {
	if pageNum < 1 || pageNum > t.book.TotalPages {
		return jsonError(fmt.Sprintf("Invalid page number: %d (book has %d pages)", pageNum, t.book.TotalPages)), nil
	}

	text, err := t.getPageBlendedText(ctx, pageNum)
	if err != nil {
		return jsonError(fmt.Sprintf("No OCR data for page %d: %v", pageNum, err)), nil
	}

	// Estimate if this is in back matter
	backMatterStart := int(float64(t.book.TotalPages) * 0.8)
	inBackMatter := pageNum >= backMatterStart

	result := map[string]any{
		"page_num":       pageNum,
		"ocr_text":       text,
		"char_count":     len(text),
		"in_back_matter": inBackMatter,
	}

	if inBackMatter {
		result["warning"] = fmt.Sprintf("This page is in the back matter region (page %d+). Check if this is actually the chapter or a footnote/endnote reference.", backMatterStart)
	}

	return jsonSuccess(result), nil
}
