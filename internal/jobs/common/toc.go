package common

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

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
		SystemPromptOverride: book.GetPrompt(extract_toc.PromptKey),
	})
	unit.ID = unitID
	unit.Provider = book.TocProvider
	unit.JobID = jc.ID()

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     jc.Type(),
		ItemKey:   "toc_extract",
		PromptKey: extract_toc.PromptKey,
		PromptCID: book.GetPromptCID(extract_toc.PromptKey),
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
// This operation is idempotent - it deletes existing entries before creating new ones.
func SaveTocExtractResult(ctx context.Context, tocDocID string, result *extract_toc.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Delete existing entries for this ToC (makes operation idempotent for retries)
	if err := DeleteExistingTocEntries(ctx, tocDocID); err != nil {
		return fmt.Errorf("failed to delete existing ToC entries: %w", err)
	}

	// Create TocEntry records for each entry
	for i, entry := range result.Entries {
		entryData := map[string]any{
			"toc_id":     tocDocID,
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

		sink.Send(defra.WriteOp{
			Collection: "TocEntry",
			Document:   entryData,
			Op:         defra.OpCreate,
		})
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

// DeleteExistingTocEntries deletes any existing TocEntry records for a ToC.
func DeleteExistingTocEntries(ctx context.Context, tocDocID string) error {
	if tocDocID == "" {
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

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		return nil // No existing entries
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
