package common

import "context"

// PageData contains all cached page content data.
type PageData struct {
	BlendMarkdown   string
	Headings        []HeadingItem
	PageNumberLabel *string
	RunningHeader   *string
}

// PageWithHeading contains page info with heading data for chapter detection.
type PageWithHeading struct {
	PageNum         int
	Heading         HeadingItem
	PageNumberLabel *string
	IsTocPage       bool
}

// PageDataReader provides cached read access to page data.
// Implementations handle lazy loading from DefraDB and batch preloading.
//
// Design principles:
//   - Cache hit: instant return from in-memory state
//   - Cache miss: single DB query, populate cache, return
//   - Batch preload: one query populates multiple pages for bulk operations
//
// This interface eliminates O(N) DB queries when tools iterate over pages.
type PageDataReader interface {
	// GetPageData returns cached page data, loading from DB if needed.
	// Returns error if page doesn't exist or DB query fails.
	GetPageData(ctx context.Context, pageNum int) (*PageData, error)

	// GetBlendedText returns just the blended markdown for a page.
	// This is a convenience method - equivalent to GetPageData().BlendMarkdown.
	GetBlendedText(ctx context.Context, pageNum int) (string, error)

	// PreloadPages batch-loads data for a range of pages in one DB query.
	// Call this before iterating over pages to avoid O(N) queries.
	// Pages already loaded are skipped (no re-fetch).
	PreloadPages(ctx context.Context, startPage, endPage int) error

	// GetPagesWithHeadings returns pages that have chapter-level headings (level 1-2).
	// Optionally filter by page range. Pass nil for no limit.
	// Excludes ToC pages (is_toc_page=true) from results.
	GetPagesWithHeadings(ctx context.Context, startPage, endPage *int) ([]PageWithHeading, error)

	// GetTotalPages returns the total number of pages in the book.
	GetTotalPages() int

	// GetBookID returns the book's document ID.
	GetBookID() string
}
