package common

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GetPage returns the page state for a given page number (thread-safe).
func (b *BookState) GetPage(pageNum int) *PageState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.Pages[pageNum]
}

// GetOrCreatePage returns the page state for a page, creating it if needed (thread-safe).
func (b *BookState) GetOrCreatePage(pageNum int) *PageState {
	b.mu.Lock()
	defer b.mu.Unlock()
	if b.Pages[pageNum] == nil {
		b.Pages[pageNum] = NewPageState()
	}
	return b.Pages[pageNum]
}

// GetPageAtCID loads a page's state at a specific DefraDB commit CID.
func (b *BookState) GetPageAtCID(ctx context.Context, pageNum int, cid string) (map[string]any, error) {
	if cid == "" {
		return nil, fmt.Errorf("cid is required")
	}
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query, vars := defra.NewQuery("Page").
		Filter("_bookID", b.BookID).
		Filter("page_num", pageNum).
		WithCID(cid).
		Fields("_docID", "page_num", "ocr_markdown", "headings", "ocr_complete").
		Build()

	resp, err := defraClient.Execute(ctx, query, vars)
	if err != nil {
		return nil, err
	}
	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return nil, fmt.Errorf("page not found at CID %s", cid)
	}
	page, ok := pages[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("unexpected page format at CID %s", cid)
	}
	return page, nil
}

// ForEachPage calls the function for each page (thread-safe, read lock).
func (b *BookState) ForEachPage(fn func(pageNum int, state *PageState)) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for pageNum, state := range b.Pages {
		fn(pageNum, state)
	}
}

// CountPages returns the number of pages in the state.
func (b *BookState) CountPages() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.Pages)
}

// CountOcrPages returns the number of pages that have OCR markdown set.
func (b *BookState) CountOcrPages() int {
	count := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsOcrMarkdownSet() {
			count++
		}
	})
	return count
}

// QuarantinedOCRPages returns the sorted page numbers carrying an explicit OCR
// quarantine. Quarantine is terminal for scheduling but degraded for output
// certification.
func (b *BookState) QuarantinedOCRPages() []int {
	var pages []int
	b.ForEachPage(func(pageNum int, state *PageState) {
		if quarantined, _ := state.OCRQuarantine(); quarantined {
			pages = append(pages, pageNum)
		}
	})
	sort.Ints(pages)
	return pages
}

// AllPagesComplete returns true if all pages have successful OCR or an explicit quarantine.
func (b *BookState) AllPagesComplete() bool {
	allDone := true
	b.ForEachPage(func(pageNum int, state *PageState) {
		if !state.OcrResolved(b.OcrProviders) {
			allDone = false
		}
	})
	return allDone && b.CountPages() >= b.TotalPages
}

// AllPagesOcrComplete returns true if all pages have successful OCR or an explicit quarantine.
func (b *BookState) AllPagesOcrComplete() bool {
	allDone := true
	b.ForEachPage(func(pageNum int, state *PageState) {
		if !state.OcrResolved(b.OcrProviders) {
			allDone = false
		}
	})
	return allDone && b.CountPages() >= b.TotalPages
}

// ConsecutivePagesComplete returns true if pages 1 through `required` have OCR
// or an explicit quarantine.
// If TotalPages < required, checks up to TotalPages.
func (b *BookState) ConsecutivePagesComplete(required int) bool {
	if b.TotalPages < required {
		required = b.TotalPages
	}
	for pageNum := 1; pageNum <= required; pageNum++ {
		state := b.GetPage(pageNum)
		if state == nil || !state.OcrResolved(b.OcrProviders) {
			return false
		}
	}
	return true
}

// ProviderProgress contains progress data for a single provider.
type ProviderProgress struct {
	TotalExpected int
	Completed     int
}

// GetProviderProgress returns progress by provider for tracking job completion.
// Includes extract and OCR per provider progress.
func (b *BookState) GetProviderProgress() map[string]ProviderProgress {
	progress := make(map[string]ProviderProgress)

	// Track extraction progress
	extractCompleted := 0
	b.ForEachPage(func(pageNum int, state *PageState) {
		if state.IsExtractDone() {
			extractCompleted++
		}
	})
	progress["extract"] = ProviderProgress{
		TotalExpected: b.TotalPages,
		Completed:     extractCompleted,
	}

	// Track OCR progress per provider
	for _, provider := range b.OcrProviders {
		completed := 0
		b.ForEachPage(func(pageNum int, state *PageState) {
			if state.OcrComplete(provider) {
				completed++
			}
		})
		progress[provider] = ProviderProgress{
			TotalExpected: b.TotalPages,
			Completed:     completed,
		}
	}

	return progress
}
