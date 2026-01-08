package common

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateTocExtractWorkUnit creates a ToC extraction work unit.
// Returns nil if no ToC pages are available.
// The caller is responsible for registering the work unit with their tracker.
func CreateTocExtractWorkUnit(ctx context.Context, jc JobContext, tocDocID string) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	logger := svcctx.LoggerFrom(ctx)

	// Get ToC page range
	tocStartPage, tocEndPage := book.GetTocPageRange()

	// Load ToC pages
	tocPages, err := LoadTocPages(ctx, book.BookID, tocStartPage, tocEndPage)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to load ToC pages", "error", err)
		}
		return nil, ""
	}
	if len(tocPages) == 0 {
		if logger != nil {
			logger.Warn("no ToC pages found",
				"start_page", tocStartPage,
				"end_page", tocEndPage)
		}
		return nil, ""
	}

	// Load structure summary from finder (if available)
	structureSummary, _ := LoadTocStructureSummary(ctx, tocDocID)

	unitID := uuid.New().String()

	unit := extract_toc.CreateWorkUnit(extract_toc.Input{
		ToCPages:             tocPages,
		StructureSummary:     structureSummary,
		SystemPromptOverride: book.GetPrompt(extract_toc.SystemPromptKey),
		UserPromptOverride:   book.GetPrompt(extract_toc.UserPromptKey),
	})
	unit.ID = unitID
	unit.Provider = book.TocProvider
	unit.JobID = jc.ID()

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     jc.Type(),
		ItemKey:   "toc_extract",
		PromptKey: extract_toc.SystemPromptKey,
		PromptCID: book.GetPromptCID(extract_toc.SystemPromptKey),
	}

	return unit, unitID
}

// LoadTocPages loads ToC page content for extraction from DefraDB.
func LoadTocPages(ctx context.Context, bookID string, startPage, endPage int) ([]extract_toc.ToCPage, error) {
	logger := svcctx.LoggerFrom(ctx)

	if startPage == 0 || endPage == 0 {
		return nil, fmt.Errorf("ToC page range not set")
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	// Build page filter - use _in for range or _eq for single page
	var pageFilter string
	if startPage == endPage {
		pageFilter = fmt.Sprintf("page_num: {_eq: %d}", startPage)
	} else {
		var pages []string
		for p := startPage; p <= endPage; p++ {
			pages = append(pages, fmt.Sprintf("%d", p))
		}
		pageFilter = fmt.Sprintf("page_num: {_in: [%s]}", strings.Join(pages, ", "))
	}

	query := fmt.Sprintf(`{
		Page(filter: {
			book_id: {_eq: "%s"},
			%s
		}, order: {page_num: ASC}) {
			page_num
			blend_markdown
		}
	}`, bookID, pageFilter)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawPages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, fmt.Errorf("no pages found in response")
	}

	if logger != nil {
		logger.Debug("LoadTocPages query result", "raw_pages_count", len(rawPages))
	}

	var tocPages []extract_toc.ToCPage
	for _, p := range rawPages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		var tp extract_toc.ToCPage
		if pn, ok := page["page_num"].(float64); ok {
			tp.PageNum = int(pn)
		}
		if bm, ok := page["blend_markdown"].(string); ok {
			tp.OCRText = bm
		}

		if tp.OCRText != "" {
			tocPages = append(tocPages, tp)
		} else if logger != nil {
			logger.Debug("page has no blend_markdown", "page_num", tp.PageNum)
		}
	}

	return tocPages, nil
}

// LoadTocStructureSummary loads the structure summary from the ToC finder.
func LoadTocStructureSummary(ctx context.Context, tocDocID string) (*extract_toc.StructureSummary, error) {
	if tocDocID == "" {
		return nil, nil
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		ToC(filter: {_docID: {_eq: "%s"}}) {
			structure_summary
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	if tocs, ok := resp.Data["ToC"].([]any); ok && len(tocs) > 0 {
		if toc, ok := tocs[0].(map[string]any); ok {
			if summaryStr, ok := toc["structure_summary"].(string); ok && summaryStr != "" {
				var summary extract_toc.StructureSummary
				if err := json.Unmarshal([]byte(summaryStr), &summary); err == nil {
					return &summary, nil
				}
			}
		}
	}

	return nil, nil
}

// SaveTocFinderResult saves the ToC finder result to DefraDB.
func SaveTocFinderResult(ctx context.Context, tocDocID string, result *toc_finder.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{
		"toc_found":       result.ToCFound,
		"finder_complete": true,
	}

	if result.ToCPageRange != nil {
		update["start_page"] = result.ToCPageRange.StartPage
		update["end_page"] = result.ToCPageRange.EndPage
	}

	if result.StructureSummary != nil {
		summaryJSON, err := json.Marshal(result.StructureSummary)
		if err == nil {
			update["structure_summary"] = string(summaryJSON)
		}
	}

	// Fire-and-forget - no need to block
	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document:   update,
		Op:         defra.OpUpdate,
	})
	return nil
}

// SaveTocFinderNoResult marks ToC finder as complete with no ToC found.
func SaveTocFinderNoResult(ctx context.Context, tocDocID string) error {
	return SendToSink(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"toc_found":       false,
			"finder_complete": true,
		},
		Op: defra.OpUpdate,
	})
}

// SaveTocExtractResult saves the ToC extraction result to DefraDB.
// This operation is idempotent - uses upsert to create or update entries.
func SaveTocExtractResult(ctx context.Context, tocDocID string, result *extract_toc.Result) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	if logger != nil {
		logger.Info("SaveTocExtractResult: upserting entries",
			"toc_doc_id", tocDocID,
			"entry_count", len(result.Entries))
	}

	// Upsert each TocEntry (filter by unique_key for uniqueness)
	for i, entry := range result.Entries {
		// unique_key ensures content-based DocID uniqueness across ToCs
		uniqueKey := fmt.Sprintf("%s:%d", tocDocID, i)

		entryData := map[string]any{
			"toc_id":     tocDocID,
			"unique_key": uniqueKey,
			"title":      entry.Title,
			"level":      entry.Level,
			"sort_order": i,
		}

		if entry.EntryNumber != nil {
			entryData["entry_number"] = *entry.EntryNumber
		}
		if entry.LevelName != nil {
			entryData["level_name"] = *entry.LevelName
		}
		if entry.PrintedPageNumber != nil {
			entryData["printed_page_number"] = *entry.PrintedPageNumber
		}

		// Filter by unique_key for upsert
		filter := map[string]any{
			"unique_key": map[string]any{"_eq": uniqueKey},
		}

		// Upsert: create if not exists, update if exists
		_, err := defraClient.Upsert(ctx, "TocEntry", filter, entryData, entryData)
		if err != nil {
			if logger != nil {
				logger.Error("SaveTocExtractResult: upsert failed",
					"sort_order", i,
					"title", entry.Title,
					"error", err)
			}
			return fmt.Errorf("failed to upsert TocEntry %d: %w", i, err)
		}
	}

	if logger != nil {
		logger.Info("SaveTocExtractResult: upserted all entries",
			"toc_doc_id", tocDocID,
			"count", len(result.Entries))
	}

	// Mark extraction complete
	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"extract_complete": true,
		},
		Op: defra.OpUpdate,
	})
	return nil
}

// LinkedTocEntry represents a ToC entry with its page link.
// Used by finalize_toc and common_structure jobs.
type LinkedTocEntry struct {
	DocID             string
	Title             string
	EntryNumber       string
	Level             int
	LevelName         string
	SortOrder         int
	ActualPage        *int   // May be nil if not linked
	ActualPageDocID   string // Page document ID if linked
	PrintedPageNumber string
	Source            string // "extracted" or "discovered"
}

// LoadLinkedEntries loads all TocEntry records with their page links from DefraDB.
// Used by both finalize_toc and common_structure jobs.
func LoadLinkedEntries(ctx context.Context, tocDocID string) ([]*LinkedTocEntry, error) {
	if tocDocID == "" {
		return nil, fmt.Errorf("ToC document ID is required")
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
			source
			actual_page {
				_docID
				page_num
			}
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawEntries, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		return nil, nil // No entries
	}

	var entries []*LinkedTocEntry
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}

		le := &LinkedTocEntry{}

		if docID, ok := entry["_docID"].(string); ok {
			le.DocID = docID
		}
		if entryNum, ok := entry["entry_number"].(string); ok {
			le.EntryNumber = entryNum
		}
		if title, ok := entry["title"].(string); ok {
			le.Title = title
		}
		if level, ok := entry["level"].(float64); ok {
			le.Level = int(level)
		}
		if levelName, ok := entry["level_name"].(string); ok {
			le.LevelName = levelName
		}
		if printedPage, ok := entry["printed_page_number"].(string); ok {
			le.PrintedPageNumber = printedPage
		}
		if sortOrder, ok := entry["sort_order"].(float64); ok {
			le.SortOrder = int(sortOrder)
		}
		if source, ok := entry["source"].(string); ok {
			le.Source = source
		}

		// Extract actual_page link
		if actualPage, ok := entry["actual_page"].(map[string]any); ok {
			if pageDocID, ok := actualPage["_docID"].(string); ok {
				le.ActualPageDocID = pageDocID
			}
			if pageNum, ok := actualPage["page_num"].(float64); ok {
				pn := int(pageNum)
				le.ActualPage = &pn
			}
		}

		if le.DocID != "" {
			entries = append(entries, le)
		}
	}

	return entries, nil
}

// DeleteExistingTocEntries deletes any existing TocEntry records for a ToC.
func DeleteExistingTocEntries(ctx context.Context, tocDocID string) error {
	logger := svcctx.LoggerFrom(ctx)

	if tocDocID == "" {
		if logger != nil {
			logger.Warn("DeleteExistingTocEntries: empty tocDocID")
		}
		return nil
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Query existing entries
	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	if logger != nil {
		logger.Info("DeleteExistingTocEntries: querying entries", "toc_doc_id", tocDocID)
	}

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		if logger != nil {
			logger.Error("DeleteExistingTocEntries: query failed", "error", err)
		}
		return err
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		if logger != nil {
			logger.Info("DeleteExistingTocEntries: no existing entries to delete",
				"toc_doc_id", tocDocID,
				"raw_type", fmt.Sprintf("%T", resp.Data["TocEntry"]))
		}
		return nil // No existing entries
	}

	if logger != nil {
		logger.Info("DeleteExistingTocEntries: found entries to delete",
			"toc_doc_id", tocDocID,
			"count", len(entries))
	}

	// Delete each entry synchronously to ensure ordering before creates
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		// Must be sync to ensure deletes complete before creates
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
		if err != nil {
			return fmt.Errorf("failed to delete TocEntry %s: %w", docID, err)
		}
	}

	return nil
}

// GetPageDocID returns the Page document ID for a given book and page number.
func GetPageDocID(ctx context.Context, bookID string, pageNum int) (string, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return "", fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_eq: %d}}) {
			_docID
		}
	}`, bookID, pageNum)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return "", err
	}

	if pages, ok := resp.Data["Page"].([]any); ok && len(pages) > 0 {
		if page, ok := pages[0].(map[string]any); ok {
			if docID, ok := page["_docID"].(string); ok {
				return docID, nil
			}
		}
	}

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Debug("page not found in database",
			"book_id", bookID,
			"page_num", pageNum)
	}
	return "", nil
}

// SaveTocEntryResult updates a TocEntry with the found page link.
// Used by link_toc operations in both process_book and standalone link_toc jobs.
func SaveTocEntryResult(ctx context.Context, bookID, entryDocID string, result *toc_entry_finder.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{}

	if result.ScanPage != nil {
		// Need to get the Page document ID for this scan page
		pageDocID, err := GetPageDocID(ctx, bookID, *result.ScanPage)
		if err != nil {
			return fmt.Errorf("failed to get page doc ID: %w", err)
		}
		if pageDocID != "" {
			update["actual_page_id"] = pageDocID
		}
	}

	if len(update) > 0 {
		sink.Send(defra.WriteOp{
			Collection: "TocEntry",
			DocID:      entryDocID,
			Document:   update,
			Op:         defra.OpUpdate,
		})
	}

	return nil
}
