package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PreloadPages batch-loads data for a range of pages in one DB query.
func (b *BookState) PreloadPages(ctx context.Context, startPage, endPage int) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Clamp range to valid page numbers
	if startPage < 1 {
		startPage = 1
	}
	if endPage > b.TotalPages {
		endPage = b.TotalPages
	}
	if startPage > endPage {
		return nil // Nothing to load
	}

	// Count how many pages actually need loading
	needsLoad := 0
	for pageNum := startPage; pageNum <= endPage; pageNum++ {
		state := b.GetPage(pageNum)
		if state != nil && !state.IsDataLoaded() {
			needsLoad++
		}
	}

	// Skip DB query if all pages already loaded
	if needsLoad == 0 {
		return nil
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Debug("batch loading page data",
			"book_id", b.BookID,
			"start_page", startPage,
			"end_page", endPage,
			"pages_to_load", needsLoad)
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
		return fmt.Errorf("preload query failed: %w", err)
	}

	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("preload query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil // No pages returned
	}

	loaded := 0
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
		if pageNum < startPage || pageNum > endPage {
			continue
		}

		state := b.GetPage(pageNum)
		if state == nil {
			continue
		}

		// Skip if already loaded
		if state.IsDataLoaded() {
			continue
		}

		// Populate cache from query result
		state.PopulateFromDBResult(page)
		loaded++
	}

	if logger != nil {
		logger.Debug("completed batch page-data load",
			"book_id", b.BookID,
			"pages_loaded", loaded)
	}

	return nil
}
