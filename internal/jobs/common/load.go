package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadBookConfig configures what to load for a book.
type LoadBookConfig struct {
	// Required
	HomeDir *home.Dir

	// Provider config
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool

	// Optional prompt resolution
	// If PromptKeys is non-empty, prompts will be resolved and stored in BookState
	// Uses GetEmbeddedDefault for fallbacks when resolver doesn't have the prompt
	PromptKeys []string
}

// LoadBookResult contains the fully loaded book state.
type LoadBookResult struct {
	Book     *BookState
	TocDocID string // ToC document ID (needed by jobs but not part of BookState)
}

// LoadBook loads everything about a book in one call:
// 1. Query DB for book record (page_count)
// 2. Load PDFs from disk
// 3. Load page states from DB
// 4. Load operation states from DB
// 5. Resolve prompts (if PromptKeys provided)
func LoadBook(ctx context.Context, bookID string, cfg LoadBookConfig) (*LoadBookResult, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	if cfg.HomeDir == nil {
		return nil, fmt.Errorf("HomeDir is required")
	}

	logger := svcctx.LoggerFrom(ctx)

	book := NewBookState(bookID)

	// 1. Query book record for page_count
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			if pc, ok := bookData["page_count"].(float64); ok {
				book.TotalPages = int(pc)
			}
		}
	}

	if book.TotalPages == 0 {
		return nil, fmt.Errorf("book %s has no pages or not found", bookID)
	}

	// 2. Set config
	book.HomeDir = cfg.HomeDir
	book.OcrProviders = cfg.OcrProviders
	book.BlendProvider = cfg.BlendProvider
	book.LabelProvider = cfg.LabelProvider
	book.MetadataProvider = cfg.MetadataProvider
	book.TocProvider = cfg.TocProvider
	book.DebugAgents = cfg.DebugAgents

	// 3. Load PDFs from disk
	pdfs, err := LoadPDFsFromOriginals(cfg.HomeDir, bookID)
	if err != nil {
		return nil, fmt.Errorf("failed to load PDFs: %w", err)
	}
	if len(pdfs) == 0 {
		return nil, fmt.Errorf("no PDFs found in originals directory for book %s", bookID)
	}
	book.PDFs = pdfs

	if logger != nil {
		logger.Debug("LoadBook: loaded PDFs", "book_id", bookID, "pdf_count", len(pdfs))
	}

	// 4. Load page states from DB
	if err := LoadPageStates(ctx, book); err != nil {
		return nil, fmt.Errorf("failed to load page states: %w", err)
	}

	if logger != nil {
		logger.Debug("LoadBook: loaded page states", "book_id", bookID, "pages", book.CountPages())
	}

	// 5. Load operation states from DB
	tocDocID, err := LoadBookOperationState(ctx, book)
	if err != nil {
		return nil, fmt.Errorf("failed to load book operation state: %w", err)
	}

	if logger != nil {
		logger.Debug("LoadBook: loaded operation states", "book_id", bookID, "toc_doc_id", tocDocID)
	}

	// 6. Resolve prompts (optional)
	if len(cfg.PromptKeys) > 0 {
		if err := ResolvePrompts(ctx, book, cfg.PromptKeys, GetEmbeddedDefault); err != nil {
			return nil, fmt.Errorf("failed to resolve prompts: %w", err)
		}

		if logger != nil {
			logger.Debug("LoadBook: resolved prompts", "book_id", bookID, "count", len(cfg.PromptKeys))
		}
	}

	if logger != nil {
		logger.Info("LoadBook: complete",
			"book_id", bookID,
			"total_pages", book.TotalPages,
			"loaded_pages", book.CountPages(),
			"toc_doc_id", tocDocID)
	}

	return &LoadBookResult{
		Book:     book,
		TocDocID: tocDocID,
	}, nil
}

// ResolvePrompts resolves prompts for a book and stores them in BookState.
// Uses the PromptResolver from context if available, falls back to defaults.
func ResolvePrompts(ctx context.Context, book *BookState, keys []string, defaults func(string) string) error {
	resolver := svcctx.PromptResolverFrom(ctx)
	logger := svcctx.LoggerFrom(ctx)

	for _, key := range keys {
		var text string
		var cid string

		if resolver != nil {
			resolved, err := resolver.Resolve(ctx, key, book.BookID)
			if err != nil {
				if logger != nil {
					logger.Warn("failed to resolve prompt, using default",
						"key", key, "book_id", book.BookID, "error", err)
				}
				// Fall through to defaults
			} else {
				text = resolved.Text
				cid = resolved.CID
				if resolved.IsOverride && logger != nil {
					logger.Info("using book-level prompt override",
						"key", key, "book_id", book.BookID)
				}
			}
		}

		// If we didn't get text from resolver, use defaults
		if text == "" && defaults != nil {
			text = defaults(key)
		}

		book.Prompts[key] = text
		book.PromptCIDs[key] = cid
	}

	return nil
}

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

		// Use thread-safe setters for all field assignments
		if docID, ok := page["_docID"].(string); ok {
			state.SetPageDocID(docID)
		}
		if extractComplete, ok := page["extract_complete"].(bool); ok {
			state.SetExtractDone(extractComplete)
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
			state.SetBlendDone(blendComplete)
		}
		if labelComplete, ok := page["label_complete"].(bool); ok {
			state.SetLabelDone(labelComplete)
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
	return NewOperationState(status, retries)
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
				link_started
				link_complete
				link_failed
				link_retries
				start_page
				end_page
			}
		}
	}`, book.BookID)

	tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
	if err != nil {
		// ToC query errors are not fatal, but log them for debugging
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("ToC query failed, proceeding without ToC state",
				"book_id", book.BookID,
				"error", err)
		}
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

				// Link state
				var lStarted, lComplete, lFailed bool
				var lRetries int
				if ls, ok := toc["link_started"].(bool); ok {
					lStarted = ls
				}
				if lc, ok := toc["link_complete"].(bool); ok {
					lComplete = lc
				}
				if lf, ok := toc["link_failed"].(bool); ok {
					lFailed = lf
				}
				if lr, ok := toc["link_retries"].(float64); ok {
					lRetries = int(lr)
				}
				book.TocLink = boolsToOpState(lStarted, lComplete, lFailed, lRetries)

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
