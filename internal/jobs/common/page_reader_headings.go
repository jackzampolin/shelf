package common

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GetPagesWithHeadings returns pages that have chapter-level headings (level 1-2).
func (b *BookState) GetPagesWithHeadings(ctx context.Context, startPage, endPage *int) ([]PageWithHeading, error) {
	// Determine range
	start := 1
	end := b.TotalPages
	if startPage != nil {
		start = *startPage
	}
	if endPage != nil {
		end = *endPage
	}

	// Preload the range first
	if err := b.PreloadPages(ctx, start, end); err != nil {
		return nil, err
	}

	var results []PageWithHeading
	for pageNum := start; pageNum <= end; pageNum++ {
		state := b.GetPage(pageNum)
		if state == nil {
			continue
		}

		headings := state.GetHeadings()
		for _, h := range headings {
			// Only chapter-level headings (level 1-2)
			if h.Level <= 2 {
				results = append(results, PageWithHeading{
					PageNum: pageNum,
					Heading: h,
				})
				break // Only first chapter heading per page
			}
		}
	}

	return results, nil
}

// GetPagesWithHeadingsFiltered returns pages with chapter headings.
// This queries DB directly to get headings for proper filtering.
func (b *BookState) GetPagesWithHeadingsFiltered(ctx context.Context, startPage, endPage *int) ([]PageWithHeading, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	// Determine range
	start := 1
	end := b.TotalPages
	if startPage != nil {
		start = *startPage
	}
	if endPage != nil {
		end = *endPage
	}

	// Note: DefraDB doesn't support _gte/_lte on Int fields without index
	// Fetch all pages for the book and filter in-memory
	query := fmt.Sprintf(`{
		Page(filter: {_bookID: {_eq: "%s"}}) {
			page_num
			ocr_markdown
			headings
			header
			footer
		}
	}`, b.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}

	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, nil // No pages
	}

	var results []PageWithHeading
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

		// Filter by requested range (since we fetch all pages)
		if pageNum < start || pageNum > end {
			continue
		}

		// Also populate cache while we're at it
		state := b.GetPage(pageNum)
		if state != nil && !state.IsDataLoaded() {
			state.PopulateFromDBResult(page)
		}

		// Parse headings
		var headings []HeadingItem
		if h, ok := page["headings"].(string); ok && h != "" {
			if err := json.Unmarshal([]byte(h), &headings); err != nil {
				if logger := svcctx.LoggerFrom(ctx); logger != nil {
					logger.Debug("failed to parse headings JSON",
						"book_id", b.BookID,
						"page_num", pageNum,
						"error", err)
				}
			}
		}

		// Find first chapter-level heading
		for _, h := range headings {
			if h.Level <= 2 {
				results = append(results, PageWithHeading{
					PageNum: pageNum,
					Heading: h,
				})
				break
			}
		}
	}

	return results, nil
}
