package tools

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/providers"
)

func loadOcrTextTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "load_ocr_text",
			Description: "Load blended OCR text for the CURRENTLY loaded page. Use this AFTER load_page_image to see clean text extraction. This helps analyze structure accurately (indentation levels, numbering patterns, entry hierarchy). Only works if a page is currently loaded.",
			Parameters:  mustMarshal(map[string]any{"type": "object", "properties": map[string]any{}, "required": []string{}}),
		},
	}
}

func (t *ToCFinderTools) loadOcrText(ctx context.Context) (string, error) {
	if t.currentPageNum == nil {
		return jsonError("No page currently loaded. Call load_page_image first."), nil
	}

	text, err := t.getPageBlendedText(ctx, *t.currentPageNum)
	if err != nil {
		return jsonError(fmt.Sprintf("No blended OCR data found for page %d. Ensure page processing has run.", *t.currentPageNum)), nil
	}

	return jsonSuccess(map[string]any{
		"page_num":   *t.currentPageNum,
		"message":    fmt.Sprintf("Blended OCR text loaded for page %d", *t.currentPageNum),
		"ocr_text":   text,
		"char_count": len(text),
	}), nil
}
