package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

// HeadingPageResult represents a page with chapter-level headings.
type HeadingPageResult struct {
	ScanPage   int             `json:"scan_page"`
	Heading    HeadingInfo     `json:"heading"`
	PageNumber *PageNumberInfo `json:"page_number,omitempty"`
	Confidence float64         `json:"confidence"`
	Excluded   bool            `json:"excluded,omitempty"`
}

// HeadingInfo describes a detected heading.
type HeadingInfo struct {
	Text  string `json:"text"`
	Level int    `json:"level"`
}

// PageNumberInfo describes a detected page number.
type PageNumberInfo struct {
	Number string `json:"number"`
}

// HeadingItem matches the structure stored in DefraDB.
type HeadingItem struct {
	Level      int    `json:"level"`
	Text       string `json:"text"`
	LineNumber int    `json:"line_number"`
}

// getHeadingPagesTool returns the tool definition for get_heading_pages.
func getHeadingPagesTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "get_heading_pages",
			Description: "Find pages with chapter-level headings (level 1-2). Returns pages where headings were detected. Useful for finding potential chapter starts.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"start_page": map[string]any{
						"type":        "integer",
						"description": "Start of page range to search (inclusive). Optional.",
					},
					"end_page": map[string]any{
						"type":        "integer",
						"description": "End of page range to search (inclusive). Optional.",
					},
				},
				"required": []string{},
			}),
		},
	}
}

// getHeadingPages finds pages with chapter-level headings.
func (t *ChapterFinderTools) getHeadingPages(ctx context.Context, startPage, endPage *int) (string, error) {
	// Query pages with headings from DefraDB
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}, order: {page_num: ASC}) {
			page_num
			headings
			page_number_label
			is_toc_page
		}
	}`, t.bookID)

	resp, err := t.defraClient.Execute(ctx, query, nil)
	if err != nil {
		return "", fmt.Errorf("failed to query pages: %w", err)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		return "[]", nil
	}

	// Get ToC page range to exclude
	tocStart, tocEnd := t.getTocPageRange(ctx)

	var results []HeadingPageResult
	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}
		if pageNum == 0 {
			continue
		}

		// Apply page range filter
		if startPage != nil && pageNum < *startPage {
			continue
		}
		if endPage != nil && pageNum > *endPage {
			continue
		}

		// Skip ToC pages
		if tocStart > 0 && tocEnd > 0 && pageNum >= tocStart && pageNum <= tocEnd {
			continue
		}
		if isToc, ok := page["is_toc_page"].(bool); ok && isToc {
			continue
		}

		// Parse headings JSON
		headingsStr, ok := page["headings"].(string)
		if !ok || headingsStr == "" {
			continue
		}

		var headings []HeadingItem
		if err := json.Unmarshal([]byte(headingsStr), &headings); err != nil {
			continue
		}

		// Filter to chapter-level headings (level 1-2)
		var chapterHeadings []HeadingItem
		for _, h := range headings {
			if h.Level <= 2 {
				chapterHeadings = append(chapterHeadings, h)
			}
		}
		if len(chapterHeadings) == 0 {
			continue
		}

		// Use first chapter heading
		firstHeading := chapterHeadings[0]

		result := HeadingPageResult{
			ScanPage: pageNum,
			Heading: HeadingInfo{
				Text:  firstHeading.Text,
				Level: firstHeading.Level,
			},
			Confidence: 0.9,
			Excluded:   t.isInExcludedRange(pageNum),
		}
		if firstHeading.Level == 2 {
			result.Confidence = 0.7
		}

		// Add page number if available
		if pnLabel, ok := page["page_number_label"].(string); ok && pnLabel != "" {
			result.PageNumber = &PageNumberInfo{Number: pnLabel}
		}

		results = append(results, result)
	}

	// Format output
	if len(results) == 0 {
		rangeDesc := "book"
		if startPage != nil || endPage != nil {
			parts := []string{}
			if startPage != nil {
				parts = append(parts, fmt.Sprintf("from page %d", *startPage))
			}
			if endPage != nil {
				parts = append(parts, fmt.Sprintf("to page %d", *endPage))
			}
			rangeDesc = strings.Join(parts, " ")
		}
		return fmt.Sprintf("No chapter-level headings found in %s.", rangeDesc), nil
	}

	// Count excluded
	excludedCount := 0
	for _, r := range results {
		if r.Excluded {
			excludedCount++
		}
	}

	output, err := json.MarshalIndent(results, "", "  ")
	if err != nil {
		return "", fmt.Errorf("failed to marshal results: %w", err)
	}

	msg := fmt.Sprintf("Found %d pages with chapter headings", len(results))
	if excludedCount > 0 {
		msg += fmt.Sprintf(" (%d in excluded ranges - skip those)", excludedCount)
	}

	return fmt.Sprintf("%s:\n%s", msg, string(output)), nil
}

// getTocPageRange returns the ToC page range for this book.
func (t *ChapterFinderTools) getTocPageRange(ctx context.Context) (start, end int) {
	query := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			toc {
				start_page
				end_page
			}
		}
	}`, t.bookID)

	resp, err := t.defraClient.Execute(ctx, query, nil)
	if err != nil {
		return 0, 0
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return 0, 0
	}

	book, ok := books[0].(map[string]any)
	if !ok {
		return 0, 0
	}

	toc, ok := book["toc"].(map[string]any)
	if !ok {
		return 0, 0
	}

	if sp, ok := toc["start_page"].(float64); ok {
		start = int(sp)
	}
	if ep, ok := toc["end_page"].(float64); ok {
		end = int(ep)
	}

	return start, end
}
