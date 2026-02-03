package common

import (
	"context"
	"encoding/json"
	"fmt"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
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
	EnableOCR             bool
	EnableMetadata        bool
	EnableTocFinder       bool
	EnableTocExtract      bool
	EnablePatternAnalysis bool
	EnableTocLink         bool
	EnableTocFinalize     bool
	EnableStructure       bool

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
	book.EnablePatternAnalysis = cfg.EnablePatternAnalysis
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
			logger.Debug("LoadBook: loaded ToC entries", "book_id", bookID, "count", len(entries))
		}
	}

	// 7. Resolve prompts (optional)
	if len(cfg.PromptKeys) > 0 {
		if err := ResolvePrompts(ctx, book, cfg.PromptKeys, GetEmbeddedDefault); err != nil {
			return nil, fmt.Errorf("failed to resolve prompts: %w", err)
		}

		if logger != nil {
			logger.Debug("LoadBook: resolved prompts", "book_id", bookID, "count", len(cfg.PromptKeys))
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
		logger.Debug("LoadBook: loaded agent states", "book_id", bookID, "count", len(book.GetAllAgentStates()))
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
			_version { cid }
			page_num
			extract_complete
			ocr_complete
			ocr_markdown
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
		docID := ""
		if v, ok := page["_docID"].(string); ok {
			docID = v
			state.SetPageDocID(docID)
		}
		cid := ""
		if versions, ok := page["_version"].([]any); ok && len(versions) > 0 {
			if v, ok := versions[0].(map[string]any); ok {
				if c, ok := v["cid"].(string); ok && c != "" {
					cid = c
					state.SetPageCID(cid)
				}
			}
		}
		book.trackCIDLocked("Page", docID, cid)
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

// loadOpStateFromData reads the 4 standard operation fields from a data map and sets the state.
// The prefix is the DB field prefix (e.g. "metadata", "finder", "extract").
func loadOpStateFromData(book *BookState, op OpType, data map[string]any, prefix string) {
	var started, complete, failed bool
	var retries int
	if v, ok := data[prefix+"_started"].(bool); ok {
		started = v
	}
	if v, ok := data[prefix+"_complete"].(bool); ok {
		complete = v
	}
	if v, ok := data[prefix+"_failed"].(bool); ok {
		failed = v
	}
	if v, ok := data[prefix+"_retries"].(float64); ok {
		retries = int(v)
	}
	book.SetOpState(op, started, complete, failed, retries)
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

	// Check book metadata, pattern analysis, and structure status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			metadata_started
			metadata_complete
			metadata_failed
			metadata_retries
			pattern_analysis_started
			pattern_analysis_complete
			pattern_analysis_failed
			pattern_analysis_retries
			page_pattern_analysis_json
			structure_started
			structure_complete
			structure_failed
			structure_retries
			structure_phase
			structure_chapters_total
			structure_chapters_extracted
			structure_chapters_polished
			structure_polish_failed
		}
	}`, book.BookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return "", err
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			// Load Book-collection operation states via registry
			loadOpStateFromData(book, OpMetadata, bookData, "metadata")
			loadOpStateFromData(book, OpPatternAnalysis, bookData, "pattern_analysis")
			loadOpStateFromData(book, OpStructure, bookData, "structure")

			// Pattern analysis result JSON (not part of standard op state)
			if paJSON, ok := bookData["page_pattern_analysis_json"].(string); ok && paJSON != "" {
				var result PagePatternResult
				if err := json.Unmarshal([]byte(paJSON), &result); err == nil {
					book.patternAnalysisResult = &result
				}
			}

			// Structure phase tracking
			if sp, ok := bookData["structure_phase"].(string); ok {
				book.structurePhase = sp
			}
			if sct, ok := bookData["structure_chapters_total"].(float64); ok {
				book.structureChaptersTotal = int(sct)
			}
			if sce, ok := bookData["structure_chapters_extracted"].(float64); ok {
				book.structureChaptersExtracted = int(sce)
			}
			if scp, ok := bookData["structure_chapters_polished"].(float64); ok {
				book.structureChaptersPolished = int(scp)
			}
			if spf, ok := bookData["structure_polish_failed"].(float64); ok {
				book.structurePolishFailed = int(spf)
			}
		}
	}

	// Check ToC status via Book relationship (ToC doesn't have book_id field)
	tocQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			toc {
				_docID
				_version { cid }
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
				finalize_started
				finalize_complete
				finalize_failed
				finalize_retries
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
				if versions, ok := toc["_version"].([]any); ok && len(versions) > 0 {
					if v, ok := versions[0].(map[string]any); ok {
						if cid, ok := v["cid"].(string); ok && cid != "" {
							book.SetTocCID(cid)
						}
					}
				}
				// Load ToC-collection operation states via registry
				loadOpStateFromData(book, OpTocFinder, toc, "finder")
				loadOpStateFromData(book, OpTocExtract, toc, "extract")
				loadOpStateFromData(book, OpTocLink, toc, "link")
				loadOpStateFromData(book, OpTocFinalize, toc, "finalize")

				if found, ok := toc["toc_found"].(bool); ok {
					book.tocFound = found
				}

				// Page range
				if sp, ok := toc["start_page"].(float64); ok {
					book.tocStartPage = int(sp)
				}
				if ep, ok := toc["end_page"].(float64); ok {
					book.tocEndPage = int(ep)
				}
			}
		}
	}

	// Store tocDocID on the book so OpConfig.DocIDSource can access it
	book.SetTocDocID(tocDocID)

	return tocDocID, nil
}

// LoadTocEntries loads all TocEntry records for a ToC that haven't been linked yet.
// Returns entries that don't have an actual_page set.
func LoadTocEntries(ctx context.Context, tocDocID string) ([]*toc_entry_finder.TocEntry, error) {
	logger := svcctx.LoggerFrom(ctx)

	if tocDocID == "" {
		if logger != nil {
			logger.Warn("LoadTocEntries: empty tocDocID")
		}
		return nil, nil // No ToC, no entries
	}

	// Validate tocDocID to prevent GraphQL injection
	if err := defra.ValidateID(tocDocID); err != nil {
		return nil, fmt.Errorf("invalid ToC doc ID: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}, order: {sort_order: ASC}) {
			_docID
			entry_number
			title
			level
			level_name
			printed_page_number
			sort_order
			actual_page {
				_docID
			}
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("LoadTocEntries: query failed", "error", err)
		}
		return nil, err
	}

	if logger != nil {
		logger.Info("LoadTocEntries: query response", "data_keys", fmt.Sprintf("%v", resp.Data))
	}

	rawEntries, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		if logger != nil {
			logger.Warn("LoadTocEntries: TocEntry not []any", "type", fmt.Sprintf("%T", resp.Data["TocEntry"]))
		}
		return nil, nil // No entries
	}

	if logger != nil {
		logger.Info("LoadTocEntries: raw entries count", "count", len(rawEntries))
	}

	var entries []*toc_entry_finder.TocEntry
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}

		// Skip entries that already have actual_page linked
		if actualPage, ok := entry["actual_page"].(map[string]any); ok {
			if _, hasDoc := actualPage["_docID"]; hasDoc {
				continue // Already linked
			}
		}

		te := &toc_entry_finder.TocEntry{}

		if docID, ok := entry["_docID"].(string); ok {
			te.DocID = docID
		}
		if entryNum, ok := entry["entry_number"].(string); ok {
			te.EntryNumber = entryNum
		}
		if title, ok := entry["title"].(string); ok {
			te.Title = title
		}
		if level, ok := entry["level"].(float64); ok {
			te.Level = int(level)
		}
		if levelName, ok := entry["level_name"].(string); ok {
			te.LevelName = levelName
		}
		if printedPage, ok := entry["printed_page_number"].(string); ok {
			te.PrintedPageNumber = printedPage
		}
		if sortOrder, ok := entry["sort_order"].(float64); ok {
			te.SortOrder = int(sortOrder)
		}

		if te.DocID != "" {
			entries = append(entries, te)
		}
	}

	return entries, nil
}

// LoadAgentStates loads all agent state records for a book from DefraDB.
// This is used for job resume - restoring agent state after a crash.
func LoadAgentStates(ctx context.Context, book *BookState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	query := fmt.Sprintf(`{
		AgentState(filter: {book_id: {_eq: "%s"}}) {
			_docID
			_version { cid }
			agent_id
			agent_type
			entry_doc_id
			iteration
			complete
			messages_json
			pending_tool_calls
			tool_results
			result_json
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		if logger != nil {
			logger.Debug("LoadAgentStates: no agent states found", "book_id", book.BookID)
		}
		return nil
	}

	for _, s := range states {
		data, ok := s.(map[string]any)
		if !ok {
			continue
		}

		state := &AgentState{}

		if docID, ok := data["_docID"].(string); ok {
			state.DocID = docID
		}
		if versions, ok := data["_version"].([]any); ok && len(versions) > 0 {
			if v, ok := versions[0].(map[string]any); ok {
				if cid, ok := v["cid"].(string); ok && cid != "" {
					state.CID = cid
				}
			}
		}
		if agentID, ok := data["agent_id"].(string); ok {
			state.AgentID = agentID
		}
		if agentType, ok := data["agent_type"].(string); ok {
			state.AgentType = agentType
		}
		if entryDocID, ok := data["entry_doc_id"].(string); ok {
			state.EntryDocID = entryDocID
		}
		if iteration, ok := data["iteration"].(float64); ok {
			state.Iteration = int(iteration)
		}
		if complete, ok := data["complete"].(bool); ok {
			state.Complete = complete
		}
		if messagesJSON, ok := data["messages_json"].(string); ok {
			state.MessagesJSON = messagesJSON
		}
		if pendingToolCalls, ok := data["pending_tool_calls"].(string); ok {
			state.PendingToolCalls = pendingToolCalls
		}
		if toolResults, ok := data["tool_results"].(string); ok {
			state.ToolResults = toolResults
		}
		if resultJSON, ok := data["result_json"].(string); ok {
			state.ResultJSON = resultJSON
		}

		if state.AgentType != "" {
			book.SetAgentState(state)
		}
	}

	if logger != nil {
		logger.Debug("LoadAgentStates: loaded states",
			"book_id", book.BookID,
			"count", len(book.agentStates))
	}

	return nil
}

// LoadFinalizeState loads finalize phase state from DefraDB.
// This includes the finalize phase from ToC and pattern analysis results from Book.
func LoadFinalizeState(ctx context.Context, book *BookState, tocDocID string) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Validate IDs to prevent GraphQL injection
	if err := defra.ValidateID(book.BookID); err != nil {
		return fmt.Errorf("invalid book ID: %w", err)
	}
	if tocDocID != "" {
		if err := defra.ValidateID(tocDocID); err != nil {
			return fmt.Errorf("invalid ToC doc ID: %w", err)
		}
	}

	logger := svcctx.LoggerFrom(ctx)

	// Load finalize phase from ToC
	if tocDocID != "" {
		tocQuery := fmt.Sprintf(`{
			ToC(filter: {_docID: {_eq: "%s"}}) {
				finalize_phase
			}
		}`, tocDocID)

		tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
		if err != nil {
			return fmt.Errorf("failed to query ToC for finalize phase: %w", err)
		}

		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if tocData, ok := tocs[0].(map[string]any); ok {
				if phase, ok := tocData["finalize_phase"].(string); ok && phase != "" {
					book.SetFinalizePhase(phase)
				}
			}
		}
	}

	// Load pattern analysis results and progress from Book
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			pattern_analysis_json
			finalize_entries_complete
			finalize_entries_found
			finalize_gaps_complete
			finalize_gaps_fixes
		}
	}`, book.BookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return fmt.Errorf("failed to query Book for finalize state: %w", err)
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			// Load pattern analysis JSON
			if paJSON, ok := bookData["pattern_analysis_json"].(string); ok && paJSON != "" {
				var data struct {
					Patterns      []DiscoveredPattern `json:"patterns"`
					Excluded      []ExcludedRange     `json:"excluded_ranges"`
					EntriesToFind []*EntryToFind      `json:"entries_to_find"`
					Reasoning     string              `json:"reasoning"`
				}
				if err := json.Unmarshal([]byte(paJSON), &data); err == nil {
					book.SetFinalizePatternResult(&FinalizePatternResult{
						Patterns:  data.Patterns,
						Excluded:  data.Excluded,
						Reasoning: data.Reasoning,
					})
					book.SetEntriesToFind(data.EntriesToFind)
				} else if logger != nil {
					logger.Warn("failed to unmarshal pattern_analysis_json", "error", err)
				}
			}

			// Load progress counters
			var entriesComplete, entriesFound, gapsComplete, gapsFixes int
			if ec, ok := bookData["finalize_entries_complete"].(float64); ok {
				entriesComplete = int(ec)
			}
			if ef, ok := bookData["finalize_entries_found"].(float64); ok {
				entriesFound = int(ef)
			}
			if gc, ok := bookData["finalize_gaps_complete"].(float64); ok {
				gapsComplete = int(gc)
			}
			if gf, ok := bookData["finalize_gaps_fixes"].(float64); ok {
				gapsFixes = int(gf)
			}
			book.SetFinalizeProgress(entriesComplete, entriesFound, gapsComplete, gapsFixes)
		}
	}

	if logger != nil {
		logger.Debug("LoadFinalizeState: loaded finalize state",
			"book_id", book.BookID,
			"phase", book.GetFinalizePhase(),
			"has_pattern_result", book.GetFinalizePatternResult() != nil)
	}

	return nil
}

// LoadStructureChapters loads all Chapter records for a book from DefraDB.
// This populates book.StructureChapters for crash recovery during structure phase.
func LoadStructureChapters(ctx context.Context, book *BookState) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	logger := svcctx.LoggerFrom(ctx)

	query := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}, order: {sort_order: ASC}) {
			_docID
			_version { cid }
			unique_key
			entry_id
			sort_order
			title
			level
			level_name
			entry_number
			start_page
			end_page
			parent_id
			source
			toc_entry_id
			matter_type
			classification_reasoning
			mechanical_text
			polished_text
			word_count
			extract_complete
			polish_complete
			polish_failed
			polish_retries
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query chapters: %w", err)
	}

	rawChapters, ok := resp.Data["Chapter"].([]any)
	if !ok || len(rawChapters) == 0 {
		if logger != nil {
			logger.Debug("LoadStructureChapters: no chapters found", "book_id", book.BookID)
		}
		return nil
	}

	var chapters []*ChapterState
	for _, c := range rawChapters {
		data, ok := c.(map[string]any)
		if !ok {
			continue
		}

		chapter := &ChapterState{}

		if docID, ok := data["_docID"].(string); ok {
			chapter.DocID = docID
		}
		if versions, ok := data["_version"].([]any); ok && len(versions) > 0 {
			if v, ok := versions[0].(map[string]any); ok {
				if cid, ok := v["cid"].(string); ok && cid != "" {
					chapter.CID = cid
				}
			}
		}
		if uniqueKey, ok := data["unique_key"].(string); ok {
			chapter.UniqueKey = uniqueKey
		}
		if entryID, ok := data["entry_id"].(string); ok {
			chapter.EntryID = entryID
		}
		if sortOrder, ok := data["sort_order"].(float64); ok {
			chapter.SortOrder = int(sortOrder)
		}
		if title, ok := data["title"].(string); ok {
			chapter.Title = title
		}
		if level, ok := data["level"].(float64); ok {
			chapter.Level = int(level)
		}
		if levelName, ok := data["level_name"].(string); ok {
			chapter.LevelName = levelName
		}
		if entryNumber, ok := data["entry_number"].(string); ok {
			chapter.EntryNumber = entryNumber
		}
		if startPage, ok := data["start_page"].(float64); ok {
			chapter.StartPage = int(startPage)
		}
		if endPage, ok := data["end_page"].(float64); ok {
			chapter.EndPage = int(endPage)
		}
		if parentID, ok := data["parent_id"].(string); ok {
			chapter.ParentID = parentID
		}
		if source, ok := data["source"].(string); ok {
			chapter.Source = source
		}
		if tocEntryID, ok := data["toc_entry_id"].(string); ok {
			chapter.TocEntryID = tocEntryID
		}
		if matterType, ok := data["matter_type"].(string); ok {
			chapter.MatterType = matterType
		}
		if reasoning, ok := data["classification_reasoning"].(string); ok {
			chapter.ClassifyReasoning = reasoning
		}
		if mechText, ok := data["mechanical_text"].(string); ok {
			chapter.MechanicalText = mechText
		}
		if polText, ok := data["polished_text"].(string); ok {
			chapter.PolishedText = polText
		}
		if wordCount, ok := data["word_count"].(float64); ok {
			chapter.WordCount = int(wordCount)
		}
		if extractDone, ok := data["extract_complete"].(bool); ok {
			chapter.ExtractDone = extractDone
		}
		if polishDone, ok := data["polish_complete"].(bool); ok {
			chapter.PolishDone = polishDone
		}
		if polishFailed, ok := data["polish_failed"].(bool); ok {
			chapter.PolishFailed = polishFailed
		}

		// Validate chapter before adding
		if chapter.DocID == "" {
			continue
		}
		// Validate page boundaries
		if chapter.StartPage < 1 {
			if logger != nil {
				logger.Warn("LoadStructureChapters: skipping chapter with invalid start_page",
					"doc_id", chapter.DocID,
					"start_page", chapter.StartPage,
					"title", chapter.Title)
			}
			continue
		}
		if chapter.EndPage > 0 && chapter.EndPage < chapter.StartPage {
			if logger != nil {
				logger.Warn("LoadStructureChapters: skipping chapter with end_page < start_page",
					"doc_id", chapter.DocID,
					"start_page", chapter.StartPage,
					"end_page", chapter.EndPage,
					"title", chapter.Title)
			}
			continue
		}
		chapters = append(chapters, chapter)
	}

	book.SetStructureChapters(chapters)

	// Also rebuild the classifications map from chapters
	classifications := make(map[string]string)
	reasonings := make(map[string]string)
	for _, ch := range chapters {
		if ch.MatterType != "" {
			classifications[ch.EntryID] = ch.MatterType
		}
		if ch.ClassifyReasoning != "" {
			reasonings[ch.EntryID] = ch.ClassifyReasoning
		}
	}
	book.SetStructureClassifications(classifications)
	book.SetStructureClassifyReasonings(reasonings)

	if logger != nil {
		logger.Debug("LoadStructureChapters: loaded chapters",
			"book_id", book.BookID,
			"count", len(chapters))
	}

	return nil
}

// loadBookMetadataFromDB loads book metadata from DefraDB.
// Returns (metadata, loaded). loaded is true when the query succeeded (even if metadata is nil).
func loadBookMetadataFromDB(ctx context.Context, bookID string) (*BookMetadata, bool) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		// No DefraDB client - expected in test contexts
		return nil, false
	}

	// Validate bookID to prevent GraphQL injection
	if err := defra.ValidateID(bookID); err != nil {
		return nil, false
	}

	logger := svcctx.LoggerFrom(ctx)

	query := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
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

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("loadBookMetadataFromDB: query failed - metadata will be unavailable",
				"book_id", bookID, "error", err)
		}
		return nil, false
	}

	books, ok := resp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		return nil, true
	}

	bookData, ok := books[0].(map[string]any)
	if !ok {
		return nil, true
	}

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

	return metadata, true
}

// loadBookCostsFromDB loads cost data from Metric records for a book.
// Aggregates costs by stage and sets total on the BookState.
// NOTE: Caller must hold the write lock on BookState.
func loadBookCostsFromDB(ctx context.Context, book *BookState) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		// No DefraDB client - costs cannot be loaded but this is expected in test contexts
		return
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query all metrics for this book
	query := fmt.Sprintf(`{
		Metric(filter: {book_id: {_eq: "%s"}}) {
			stage
			cost_usd
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("loadBookCostsFromDB: query failed - cost data will be unavailable",
				"book_id", book.BookID, "error", err)
		}
		// Don't set costsLoaded=true on error - allows retry on next access
		return
	}

	metrics, ok := resp.Data["Metric"].([]any)
	if !ok || len(metrics) == 0 {
		book.costsLoaded = true
		return
	}

	// Aggregate costs by stage
	costsByStage := make(map[string]float64)
	var totalCost float64

	for _, m := range metrics {
		metric, ok := m.(map[string]any)
		if !ok {
			continue
		}

		var stage string
		var costUSD float64

		if s, ok := metric["stage"].(string); ok {
			stage = s
		}
		if c, ok := metric["cost_usd"].(float64); ok {
			costUSD = c
		}

		if stage != "" && costUSD > 0 {
			costsByStage[stage] += costUSD
			totalCost += costUSD
		}
	}

	book.costsByStage = costsByStage
	book.totalCost = totalCost
	book.costsLoaded = true

	if logger != nil {
		logger.Debug("loadBookCostsFromDB: loaded costs",
			"book_id", book.BookID,
			"total_cost", totalCost,
			"stages", len(costsByStage))
	}
}

// loadAgentRunsFromDB loads agent run summaries from DefraDB for a book.
// NOTE: Caller must hold the write lock on BookState.
func loadAgentRunsFromDB(ctx context.Context, book *BookState) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		// No DefraDB client - agent runs cannot be loaded but this is expected in test contexts
		return
	}

	logger := svcctx.LoggerFrom(ctx)

	// Query all agent runs for this book
	query := fmt.Sprintf(`{
		AgentRun(filter: {book_id: {_eq: "%s"}}) {
			_docID
			agent_type
			job_id
			started_at
			completed_at
			iterations
			success
			error
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("loadAgentRunsFromDB: query failed - agent run history will be unavailable",
				"book_id", book.BookID, "error", err)
		}
		// Don't set agentRunsLoaded=true on error - allows retry on next access
		return
	}

	runs, ok := resp.Data["AgentRun"].([]any)
	if !ok || len(runs) == 0 {
		book.agentRunsLoaded = true
		return
	}

	// Parse agent runs into summaries
	var summaries []AgentRunSummary
	for _, r := range runs {
		run, ok := r.(map[string]any)
		if !ok {
			continue
		}

		summary := AgentRunSummary{}

		if v, ok := run["_docID"].(string); ok {
			summary.DocID = v
		}
		if v, ok := run["agent_type"].(string); ok {
			summary.AgentType = v
		}
		if v, ok := run["job_id"].(string); ok {
			summary.JobID = v
		}
		if v, ok := run["started_at"].(string); ok {
			summary.StartedAt = v
		}
		if v, ok := run["completed_at"].(string); ok {
			summary.CompletedAt = v
		}
		if v, ok := run["iterations"].(float64); ok {
			summary.Iterations = int(v)
		}
		if v, ok := run["success"].(bool); ok {
			summary.Success = v
		}
		if v, ok := run["error"].(string); ok {
			summary.Error = v
		}

		if summary.DocID != "" {
			summaries = append(summaries, summary)
		}
	}

	book.agentRuns = summaries
	book.agentRunsLoaded = true

	if logger != nil {
		logger.Debug("loadAgentRunsFromDB: loaded agent runs",
			"book_id", book.BookID,
			"count", len(summaries))
	}
}
