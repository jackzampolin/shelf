package common

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GetPageData returns cached page data, loading from DB if not cached.
func (b *BookState) GetPageData(ctx context.Context, pageNum int) (*PageData, error) {
	state := b.GetPage(pageNum)
	if state == nil {
		return nil, fmt.Errorf("page %d not found in book state", pageNum)
	}

	// Check if data is already loaded
	if state.IsDataLoaded() {
		return &PageData{
			OcrMarkdown: state.GetOcrMarkdown(),
			Headings:    state.GetHeadings(),
		}, nil
	}

	// Lazy load from DB
	if err := b.loadPageDataFromDB(ctx, pageNum, state); err != nil {
		return nil, fmt.Errorf("failed to load page %d data: %w", pageNum, err)
	}

	return &PageData{
		OcrMarkdown: state.GetOcrMarkdown(),
		Headings:    state.GetHeadings(),
	}, nil
}

// GetOcrMarkdown returns just the OCR markdown for a page.
func (b *BookState) GetOcrMarkdown(ctx context.Context, pageNum int) (string, error) {
	state := b.GetPage(pageNum)
	if state == nil {
		return "", fmt.Errorf("page %d not found in book state", pageNum)
	}

	// If data is loaded, return from cache
	if state.IsDataLoaded() {
		return state.GetOcrMarkdown(), nil
	}

	// Check if we have ocrMarkdown cached (from write-through) even if dataLoaded is false
	if text := state.GetOcrMarkdown(); text != "" {
		return text, nil
	}

	// Lazy load from DB
	if err := b.loadPageDataFromDB(ctx, pageNum, state); err != nil {
		return "", fmt.Errorf("failed to load page %d data: %w", pageNum, err)
	}

	return state.GetOcrMarkdown(), nil
}

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
		Page(filter: {book_id: {_eq: "%s"}}) {
			page_num
			ocr_markdown
			headings
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

// GetTotalPages returns the total number of pages in the book.
func (b *BookState) GetTotalPages() int {
	return b.TotalPages
}

// GetBookID returns the book's document ID.
func (b *BookState) GetBookID() string {
	return b.BookID
}

// loadPageDataFromDB loads a single page's data from DB into the cache.
func (b *BookState) loadPageDataFromDB(ctx context.Context, pageNum int, state *PageState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_eq: %d}}) {
			ocr_markdown
			headings
		}
	}`, b.BookID, pageNum)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return fmt.Errorf("page not found in database")
	}

	page, ok := pages[0].(map[string]any)
	if !ok {
		return fmt.Errorf("invalid page format")
	}

	state.PopulateFromDBResult(page)
	return nil
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
		Page(filter: {book_id: {_eq: "%s"}}) {
			page_num
			ocr_markdown
			headings
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
