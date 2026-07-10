package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Keep resume queries small enough to fit comfortably inside DefraDB's request
// timeout even when every page carries a large nested OCR result. Large books
// routinely exceed 1,000 pages, so loading the entire relationship graph in one
// response makes an otherwise durable process-book job impossible to kick.
const loadPageStatesBatchSize = 100

// LoadPageStates loads all page state from DefraDB for a book into the BookState.
func LoadPageStates(ctx context.Context, book *BookState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	for offset := 0; ; offset += loadPageStatesBatchSize {
		// Query pages with their related OCR results. Ordering is required so
		// limit/offset pages form a stable, non-overlapping snapshot.
		// Note: _version { cid } omitted because DefraDB returns 500 on empty
		// result sets. Page CIDs are captured at write time via
		// SendTracked/TrackWrite.
		query := fmt.Sprintf(`{
		Page(filter: {_bookID: {_eq: "%s"}}, order: {page_num: ASC}, limit: %d, offset: %d) {
			_docID
			page_num
			extract_complete
			ocr_complete
			ocr_markdown
			header
			footer
			headings
			ocr_results {
				provider
				text
			}
		}
	}`, book.BookID, loadPageStatesBatchSize, offset)

		resp, err := defraClient.Execute(ctx, query, nil)
		if err != nil {
			return fmt.Errorf("page-state batch offset %d: %w", offset, err)
		}

		if errMsg := resp.Error(); errMsg != "" {
			return fmt.Errorf("page-state batch offset %d query error: %s", offset, errMsg)
		}

		pages, ok := resp.Data["Page"].([]any)
		if !ok || len(pages) == 0 {
			return nil // No pages yet, or pagination is complete.
		}

		book.mu.Lock()
		for _, p := range pages {
			loadPageState(book, p)
		}
		book.mu.Unlock()

		if len(pages) < loadPageStatesBatchSize {
			return nil
		}
	}
}

// loadPageState merges one DefraDB Page result into book. The caller holds
// book.mu so a resume cannot expose a partially populated page to other work.
func loadPageState(book *BookState, raw any) {
	page, ok := raw.(map[string]any)
	if !ok {
		return
	}

	pageNum := 0
	if pn, ok := page["page_num"].(float64); ok {
		pageNum = int(pn)
	}
	if pageNum == 0 {
		return
	}

	state := NewPageState()

	// Use thread-safe setters for all field assignments.
	if v, ok := page["_docID"].(string); ok {
		state.SetPageDocID(v)
	}
	if extractComplete, ok := page["extract_complete"].(bool); ok {
		state.SetExtractDone(extractComplete)
	}
	if header, ok := page["header"].(string); ok {
		state.SetHeader(header)
	}
	if footer, ok := page["footer"].(string); ok {
		state.SetFooter(footer)
	}

	// Load OCR results from the relationship.
	if ocrResults, ok := page["ocr_results"].([]any); ok {
		for _, r := range ocrResults {
			result, ok := r.(map[string]any)
			if !ok {
				continue
			}
			provider, _ := result["provider"].(string)
			text, _ := result["text"].(string)
			if provider != "" {
				// Mark as complete even if text is empty (blank page).
				state.MarkOcrComplete(provider, text)
			}
		}
	}

	// Load OCR markdown/headings if available (for pattern analysis on resume).
	ocrComplete, _ := page["ocr_complete"].(bool)
	if ocrComplete {
		state.PopulateFromDBResult(page)

		// If OCR markdown wasn't persisted yet, derive it from OCR results.
		if state.GetOcrMarkdown() == "" {
			ocrText := ""
			for _, provider := range book.OcrProviders {
				if text, ok := state.GetOcrResult(provider); ok && text != "" {
					ocrText = text
					break
				}
			}
			if ocrText != "" {
				headings := ExtractHeadings(ocrText)
				state.SetOcrMarkdownWithHeadings(ocrText, headings)
			}
		}
	} else {
		if ocrMarkdown, ok := page["ocr_markdown"].(string); ok && ocrMarkdown != "" {
			state.PopulateFromDBResult(page)
		} else if headings, ok := page["headings"].(string); ok && headings != "" {
			state.PopulateFromDBResult(page)
		}
	}

	book.Pages[pageNum] = state
}
