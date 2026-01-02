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
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			_docID
			page_num
			extract_complete
			blend_complete
			label_complete
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

		if docID, ok := page["_docID"].(string); ok {
			state.PageDocID = docID
		}
		if extractComplete, ok := page["extract_complete"].(bool); ok {
			state.ExtractDone = extractComplete
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

		if blendComplete, ok := page["blend_complete"].(bool); ok {
			state.BlendDone = blendComplete
		}
		if labelComplete, ok := page["label_complete"].(bool); ok {
			state.LabelDone = labelComplete
		}

		book.Pages[pageNum] = state
	}

	return nil
}

// boolsToOpState converts DB boolean fields to OperationState.
func boolsToOpState(started, complete, failed bool, retries int) OperationState {
	var status OpStatus
	switch {
	case failed:
		status = OpFailed
	case complete:
		status = OpComplete
	case started:
		status = OpInProgress
	default:
		status = OpNotStarted
	}
	return OperationState{Status: status, Retries: retries}
}

// LoadBookOperationState loads book-level operation state from DefraDB.
// Returns the ToC document ID if found.
func LoadBookOperationState(ctx context.Context, book *BookState) (tocDocID string, err error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return "", fmt.Errorf("defra client not in context")
	}

	// Check book metadata status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			metadata_started
			metadata_complete
			metadata_failed
			metadata_retries
		}
	}`, book.BookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return "", err
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			var started, complete, failed bool
			var retries int
			if ms, ok := bookData["metadata_started"].(bool); ok {
				started = ms
			}
			if mc, ok := bookData["metadata_complete"].(bool); ok {
				complete = mc
			}
			if mf, ok := bookData["metadata_failed"].(bool); ok {
				failed = mf
			}
			if mr, ok := bookData["metadata_retries"].(float64); ok {
				retries = int(mr)
			}
			book.Metadata = boolsToOpState(started, complete, failed, retries)
		}
	}

	// Check ToC status via Book relationship (ToC doesn't have book_id field)
	tocQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			toc {
				_docID
				toc_found
				finder_started
				finder_complete
				finder_failed
				finder_retries
				extract_started
				extract_complete
				extract_failed
				extract_retries
				start_page
				end_page
			}
		}
	}`, book.BookID)

	tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
	if err != nil {
		// ToC query errors are not fatal
		return "", nil
	}

	if books, ok := tocResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			if toc, ok := bookData["toc"].(map[string]any); ok {
				if docID, ok := toc["_docID"].(string); ok {
					tocDocID = docID
				}
				// Finder state
				var fStarted, fComplete, fFailed bool
				var fRetries int
				if fs, ok := toc["finder_started"].(bool); ok {
					fStarted = fs
				}
				if fc, ok := toc["finder_complete"].(bool); ok {
					fComplete = fc
				}
				if ff, ok := toc["finder_failed"].(bool); ok {
					fFailed = ff
				}
				if fr, ok := toc["finder_retries"].(float64); ok {
					fRetries = int(fr)
				}
				book.TocFinder = boolsToOpState(fStarted, fComplete, fFailed, fRetries)

				if found, ok := toc["toc_found"].(bool); ok {
					book.TocFound = found
				}

				// Extract state
				var eStarted, eComplete, eFailed bool
				var eRetries int
				if es, ok := toc["extract_started"].(bool); ok {
					eStarted = es
				}
				if ec, ok := toc["extract_complete"].(bool); ok {
					eComplete = ec
				}
				if ef, ok := toc["extract_failed"].(bool); ok {
					eFailed = ef
				}
				if er, ok := toc["extract_retries"].(float64); ok {
					eRetries = int(er)
				}
				book.TocExtract = boolsToOpState(eStarted, eComplete, eFailed, eRetries)

				// Page range
				if sp, ok := toc["start_page"].(float64); ok {
					book.TocStartPage = int(sp)
				}
				if ep, ok := toc["end_page"].(float64); ok {
					book.TocEndPage = int(ep)
				}
			}
		}
	}

	return tocDocID, nil
}
