package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadBookConfig configures what to load for a book.
type LoadBookConfig struct {
	// Required
	HomeDir *home.Dir

	// Provider config
	OcrProviders     []string
	MetadataProvider string
	TocProvider      string
	DebugAgents      bool

	// Pipeline stage toggles (all default to false - should be set by variant)
	EnableOCR         bool
	EnableMetadata    bool
	EnableTocFinder   bool
	EnableTocExtract  bool
	EnableTocLink     bool
	EnableTocFinalize bool
	EnableStructure   bool

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
	// Validate bookID to prevent GraphQL injection
	if err := defra.ValidateID(bookID); err != nil {
		return nil, fmt.Errorf("invalid book ID: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	if cfg.HomeDir == nil {
		return nil, fmt.Errorf("HomeDir is required")
	}

	logger := svcctx.LoggerFrom(ctx)

	book := NewBookState(bookID)

	// 1. Query book record for page_count and metadata
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			_version { cid }
			page_count
			title
			author
			isbn
			lccn
			publisher
			publication_year
			language
			description
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			if versions, ok := bookData["_version"].([]any); ok && len(versions) > 0 {
				if v, ok := versions[0].(map[string]any); ok {
					if cid, ok := v["cid"].(string); ok && cid != "" {
						book.SetBookCID(cid)
					}
				}
			}
			if pc, ok := bookData["page_count"].(float64); ok {
				book.TotalPages = int(pc)
			}
			// Load metadata into BookMetadata struct
			metadata := &BookMetadata{}
			if v, ok := bookData["title"].(string); ok {
				metadata.Title = v
			}
			if v, ok := bookData["author"].(string); ok {
				metadata.Author = v
			}
			if v, ok := bookData["isbn"].(string); ok {
				metadata.ISBN = v
			}
			if v, ok := bookData["lccn"].(string); ok {
				metadata.LCCN = v
			}
			if v, ok := bookData["publisher"].(string); ok {
				metadata.Publisher = v
			}
			if v, ok := bookData["publication_year"].(float64); ok {
				metadata.PublicationYear = int(v)
			}
			if v, ok := bookData["language"].(string); ok {
				metadata.Language = v
			}
			if v, ok := bookData["description"].(string); ok {
				metadata.Description = v
			}
			book.SetBookMetadata(metadata)
		}
	}

	if book.TotalPages == 0 {
		return nil, fmt.Errorf("book %s has no pages or not found", bookID)
	}

	// 2. Set config
	book.HomeDir = cfg.HomeDir
	book.OcrProviders = cfg.OcrProviders
	book.MetadataProvider = cfg.MetadataProvider
	book.TocProvider = cfg.TocProvider
	book.DebugAgents = cfg.DebugAgents

	// Pipeline stage toggles
	book.EnableOCR = cfg.EnableOCR
	book.EnableMetadata = cfg.EnableMetadata
	book.EnableTocFinder = cfg.EnableTocFinder
	book.EnableTocExtract = cfg.EnableTocExtract
	book.EnableTocLink = cfg.EnableTocLink
	book.EnableTocFinalize = cfg.EnableTocFinalize
	book.EnableStructure = cfg.EnableStructure

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
		logger.Debug("loaded PDFs for book state", "book_id", bookID, "pdf_count", len(pdfs))
	}

	// 4. Load page states from DB
	if err := LoadPageStates(ctx, book); err != nil {
		return nil, fmt.Errorf("failed to load page states: %w", err)
	}

	if logger != nil {
		logger.Debug("loaded page states", "book_id", bookID, "pages", book.CountPages())
	}

	// 5. Load operation states from DB
	tocDocID, err := LoadBookOperationState(ctx, book)
	if err != nil {
		return nil, fmt.Errorf("failed to load book operation state: %w", err)
	}

	if logger != nil {
		logger.Debug("loaded operation states", "book_id", bookID, "toc_doc_id", tocDocID)
	}

	// 6. Load ToC entries if extraction is complete (for link_toc phase)
	// This is FATAL if extraction is complete - link_toc phase requires entries
	if tocDocID != "" && book.TocExtractIsComplete() {
		entries, err := LoadTocEntries(ctx, tocDocID)
		if err != nil {
			// Fatal when extraction is complete - link_toc will fail without entries
			return nil, fmt.Errorf("failed to load ToC entries for completed extraction: %w", err)
		}
		book.SetTocEntries(entries)
		if logger != nil {
			logger.Debug("loaded ToC entries", "book_id", bookID, "count", len(entries))
		}
	}

	// 7. Resolve prompts (optional)
	if len(cfg.PromptKeys) > 0 {
		if err := ResolvePrompts(ctx, book, cfg.PromptKeys, GetEmbeddedDefault); err != nil {
			return nil, fmt.Errorf("failed to resolve prompts: %w", err)
		}

		if logger != nil {
			logger.Debug("resolved prompts", "book_id", bookID, "count", len(cfg.PromptKeys))
		}
	}

	// 8. Load agent states (for job resume)
	if err := LoadAgentStates(ctx, book); err != nil {
		// Log at ERROR because job resume will fall back to restarting agents,
		// potentially incurring duplicate LLM API costs
		if logger != nil {
			logger.Error("failed to load agent states - job resume will restart agents from scratch",
				"book_id", bookID, "error", err, "impact", "potential duplicate LLM API costs")
		}
	} else if logger != nil && len(book.GetAllAgentStates()) > 0 {
		logger.Debug("loaded agent states", "book_id", bookID, "count", len(book.GetAllAgentStates()))
	}

	// 9. Load finalize state if finalize is in progress (for crash recovery)
	if book.TocFinalizeIsStarted() && !book.TocFinalizeIsDone() {
		if err := LoadFinalizeState(ctx, book, tocDocID); err != nil {
			// Log at ERROR because crash recovery will restart finalize from the beginning
			if logger != nil {
				logger.Error("failed to load finalize state - crash recovery will restart finalize phase",
					"book_id", bookID, "error", err)
			}
		}
	}

	// 10. Load structure chapters if structure is in progress (for crash recovery)
	if book.StructureIsStarted() && !book.StructureIsDone() {
		if err := LoadStructureChapters(ctx, book); err != nil {
			// Log at ERROR because crash recovery will restart structure from the beginning
			if logger != nil {
				logger.Error("failed to load structure chapters - crash recovery will restart structure phase",
					"book_id", bookID, "error", err)
			}
		}
	}

	if logger != nil {
		logger.Debug("book state load complete",
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
