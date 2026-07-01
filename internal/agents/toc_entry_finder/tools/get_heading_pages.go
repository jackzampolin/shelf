package tools

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

// HeadingPageResult represents a page with chapter-level headings.
type HeadingPageResult struct {
	ScanPage               int         `json:"scan_page"`
	Heading                HeadingInfo `json:"heading"`
	Confidence             float64     `json:"confidence"`
	TargetTitleMatch       bool        `json:"target_title_match,omitempty"`
	TargetTitlePrefixMatch bool        `json:"target_title_prefix_match,omitempty"`
	EntryNumberMatch       bool        `json:"entry_number_match,omitempty"`
	InExpectedScanWindow   bool        `json:"in_expected_scan_window,omitempty"`
}

// HeadingInfo describes a detected heading.
type HeadingInfo struct {
	Text  string `json:"text"`
	Level int    `json:"level"`
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
			Description: "Find pages with chapter-level headings (level 1-2). Returns pages where headings were detected, ranked by target-title matches and expected scan window. Faster than grep for initial exploration.",
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
	if startPage != nil && endPage != nil && *startPage > *endPage {
		*startPage, *endPage = *endPage, *startPage
	}

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

		result := t.bestHeadingPageResult(pageNum, chapterHeadings)

		results = append(results, result)
	}

	sort.SliceStable(results, func(i, j int) bool {
		return headingPageResultLess(results[i], results[j])
	})

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

func (t *TocEntryFinderTools) bestHeadingPageResult(pageNum int, headings []HeadingItem) HeadingPageResult {
	var best HeadingPageResult
	pageTargetTitleMatch := false
	pageTargetTitlePrefixMatch := false
	pageEntryNumberMatch := false
	for i, h := range headings {
		candidate := t.headingPageResult(pageNum, h)
		pageTargetTitleMatch = pageTargetTitleMatch || candidate.TargetTitleMatch
		pageTargetTitlePrefixMatch = pageTargetTitlePrefixMatch || candidate.TargetTitlePrefixMatch
		pageEntryNumberMatch = pageEntryNumberMatch || candidate.EntryNumberMatch
		if i == 0 || headingPageResultLess(candidate, best) {
			best = candidate
		}
	}
	best.TargetTitleMatch = pageTargetTitleMatch
	best.TargetTitlePrefixMatch = pageTargetTitlePrefixMatch
	best.EntryNumberMatch = pageEntryNumberMatch
	if pageTargetTitleMatch || pageTargetTitlePrefixMatch || pageEntryNumberMatch {
		best.Confidence = 1.0
	}
	return best
}

func (t *TocEntryFinderTools) headingPageResult(pageNum int, heading HeadingItem) HeadingPageResult {
	result := HeadingPageResult{
		ScanPage: pageNum,
		Heading: HeadingInfo{
			Text:  heading.Text,
			Level: heading.Level,
		},
		Confidence: 0.9,
	}
	if heading.Level == 2 {
		result.Confidence = 0.7
	}

	if t != nil && t.entry != nil {
		result.TargetTitleMatch = normalizedContains(heading.Text, t.entry.Title)
		result.TargetTitlePrefixMatch = sectionHeaderMatchesTitlePrefix([]string{heading.Text}, t.entry.Title, t.entryNumber())
		result.EntryNumberMatch = t.entryNumberFound(heading.Text) || t.entryNumberPrefixInSectionHeader([]string{heading.Text})
		if result.TargetTitleMatch || result.TargetTitlePrefixMatch || result.EntryNumberMatch {
			result.Confidence = 1.0
		}
	}
	if start, end, ok := t.expectedScanWindow(); ok {
		result.InExpectedScanWindow = pageNum >= start && pageNum <= end
	}

	return result
}

func headingPageResultLess(a, b HeadingPageResult) bool {
	aScore := headingPageResultScore(a)
	bScore := headingPageResultScore(b)
	if aScore != bScore {
		return aScore > bScore
	}
	if a.Confidence != b.Confidence {
		return a.Confidence > b.Confidence
	}
	return a.ScanPage < b.ScanPage
}

func headingPageResultScore(result HeadingPageResult) int {
	score := 0
	if result.TargetTitleMatch {
		score += 100
	}
	if result.TargetTitlePrefixMatch {
		score += 90
	}
	if result.EntryNumberMatch {
		score += 30
	}
	if result.InExpectedScanWindow {
		score += 10
	}
	return score
}
