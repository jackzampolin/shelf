package tools

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

// HeadingPageResult represents a page with chapter-level headings.
type HeadingPageResult struct {
	ScanPage   int                    `json:"scan_page"`
	Heading    HeadingInfo            `json:"heading"`
	PageNumber *PageNumberInfo        `json:"page_number,omitempty"`
	Confidence float64                `json:"confidence"`
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
			Description: "Find pages with chapter-level headings (level 1-2). Returns pages where headings were detected, useful for finding potential chapter starts. Faster than grep for initial exploration.",
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

// getHeadingPages finds pages with chapter-level headings using BookState.
func (t *TocEntryFinderTools) getHeadingPages(startPage, endPage *int) (string, error) {
	// Get ToC page range to exclude
	tocStart, tocEnd := t.book.GetTocPageRange()

	var results []HeadingPageResult

	// Iterate through pages in BookState
	for pageNum := 1; pageNum <= t.book.TotalPages; pageNum++ {
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

		page := t.book.GetPage(pageNum)
		if page == nil {
			continue
		}

		// Skip if marked as ToC page
		if isToc := page.GetIsTocPage(); isToc != nil && *isToc {
			continue
		}

		// Get headings from page state
		headings := page.GetHeadings()
		if len(headings) == 0 {
			continue
		}

		// Filter to chapter-level headings (level 1-2)
		var chapterHeadings []HeadingItem
		for _, h := range headings {
			if h.Level <= 2 {
				chapterHeadings = append(chapterHeadings, HeadingItem{
					Level:      h.Level,
					Text:       h.Text,
					LineNumber: h.LineNumber,
				})
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
		}
		if firstHeading.Level == 2 {
			result.Confidence = 0.7
		}

		// Add page number if available
		if pnLabel := page.GetPageNumberLabel(); pnLabel != nil && *pnLabel != "" {
			result.PageNumber = &PageNumberInfo{Number: *pnLabel}
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

	output, err := json.MarshalIndent(results, "", "  ")
	if err != nil {
		return "", fmt.Errorf("failed to marshal results: %w", err)
	}

	return fmt.Sprintf("Found %d pages with chapter headings:\n%s", len(results), string(output)), nil
}

