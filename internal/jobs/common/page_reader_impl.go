package common

import (
	"context"
	"fmt"
	stdhtml "html"
	"strings"

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

// GetOcrMarkdownWithPageFurniture returns OCR markdown plus synthetic labeled
// page-header/footer blocks when the OCR provider stored those separately.
// This keeps content extraction clean while preserving running-header evidence
// for ToC/chapter linking agents.
func (b *BookState) GetOcrMarkdownWithPageFurniture(ctx context.Context, pageNum int) (string, error) {
	text, err := b.GetOcrMarkdown(ctx, pageNum)
	if err != nil {
		return "", err
	}
	if text == "" || strings.Contains(text, "data-label=") {
		return text, nil
	}

	state := b.GetPage(pageNum)
	if state == nil {
		return text, nil
	}
	header := state.GetHeader()
	footer := state.GetFooter()
	if strings.TrimSpace(header) == "" && strings.TrimSpace(footer) == "" {
		return text, nil
	}

	var parts []string
	for _, line := range splitPageFurnitureLines(header) {
		parts = append(parts, fmt.Sprintf(`<div data-label="Page-Header">%s</div>`, stdhtml.EscapeString(line)))
	}
	parts = append(parts, text)
	for _, line := range splitPageFurnitureLines(footer) {
		parts = append(parts, fmt.Sprintf(`<div data-label="Page-Footer">%s</div>`, stdhtml.EscapeString(line)))
	}
	return strings.Join(parts, "\n"), nil
}

func splitPageFurnitureLines(text string) []string {
	var lines []string
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			lines = append(lines, line)
		}
	}
	return lines
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
		Page(filter: {_bookID: {_eq: "%s"}, page_num: {_eq: %d}}) {
			ocr_markdown
			headings
			header
			footer
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
