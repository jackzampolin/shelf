package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadPageStates loads all page state from DefraDB for a book into the BookState.
func LoadPageStates(ctx context.Context, book *BookState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Query pages with their related OCR results
	// Note: _version { cid } omitted because DefraDB returns 500 on empty result sets.
	// Page CIDs are captured at write time via SendTracked/TrackWrite.
	query := fmt.Sprintf(`{
		Page(filter: {_bookID: {_eq: "%s"}}) {
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
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil // No pages yet
	}

	book.mu.Lock()
	defer book.mu.Unlock()

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

		state := NewPageState()

		// Use thread-safe setters for all field assignments
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

		// Load OCR results from the relationship
		if ocrResults, ok := page["ocr_results"].([]any); ok {
			for _, r := range ocrResults {
				result, ok := r.(map[string]any)
				if !ok {
					continue
				}
				provider, _ := result["provider"].(string)
				text, _ := result["text"].(string)
				if provider != "" {
					// Mark as complete even if text is empty (blank page)
					state.MarkOcrComplete(provider, text)
				}
			}
		}

		// Load OCR markdown/headings if available (for pattern analysis on resume)
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

	return nil
}
