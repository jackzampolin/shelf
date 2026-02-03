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
			Description: "Load OCR markdown text for the CURRENTLY loaded page. Use this AFTER load_page_image to see clean text extraction. This helps analyze structure accurately (indentation levels, numbering patterns, entry hierarchy). Only works if a page is currently loaded.",
			Parameters:  mustMarshal(map[string]any{"type": "object", "properties": map[string]any{}, "required": []string{}}),
		},
	}
}

func (t *ToCFinderTools) loadOcrText(ctx context.Context) (string, error) {
	if t.currentPageNum == nil {
		return jsonError("No page currently loaded. Call load_page_image first."), nil
	}

	text, err := t.getPageOcrMarkdown(ctx, *t.currentPageNum)
	if err != nil {
		// Check if this page was in the failed_pages list from grep report
		isKnownFailed := false
		if t.grepReportCache != nil {
			for _, fp := range t.grepReportCache.FailedPages {
				if fp == *t.currentPageNum {
					isKnownFailed = true
					break
				}
			}
		}

		if isKnownFailed {
			return jsonError(fmt.Sprintf(
				"Page %d is in failed_pages list (not yet processed). SKIP this page and check a different one. Use grep report's categorized_pages to find pages WITH data.",
				*t.currentPageNum)), nil
		}
		return jsonError(fmt.Sprintf("No OCR markdown data for page %d.", *t.currentPageNum)), nil
	}

	return jsonSuccess(map[string]any{
		"page_num":   *t.currentPageNum,
		"message":    fmt.Sprintf("OCR markdown text loaded for page %d", *t.currentPageNum),
		"ocr_text":   text,
		"char_count": len(text),
	}), nil
}
