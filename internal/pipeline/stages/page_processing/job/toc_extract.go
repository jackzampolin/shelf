package job

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/pipeline/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateTocExtractWorkUnit creates a ToC extraction work unit.
func (j *Job) CreateTocExtractWorkUnit(ctx context.Context) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Load ToC pages
	tocPages, err := j.loadTocPages(ctx)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to load ToC pages", "error", err)
		}
		return nil
	}
	if len(tocPages) == 0 {
		if logger != nil {
			logger.Warn("no ToC pages found",
				"start_page", j.BookState.TocStartPage,
				"end_page", j.BookState.TocEndPage)
		}
		return nil
	}

	// Load structure summary from finder (if available)
	structureSummary, _ := j.loadTocStructureSummary(ctx)

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: "toc_extract",
	})

	unit := extract_toc.CreateWorkUnit(extract_toc.Input{
		ToCPages:         tocPages,
		StructureSummary: structureSummary,
	})
	unit.ID = unitID
	unit.Provider = j.TocProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = "toc_extract"
	unit.Metrics = metrics

	return unit
}

// HandleTocExtractComplete processes ToC extraction completion.
func (j *Job) HandleTocExtractComplete(ctx context.Context, result jobs.WorkResult) error {
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		j.BookState.TocExtractDone = true
		return nil
	}

	extractResult, err := extract_toc.ParseResult(result.ChatResult.ParsedJSON)
	if err != nil {
		j.BookState.TocExtractDone = true
		return fmt.Errorf("failed to parse ToC extract result: %w", err)
	}

	if err := j.saveTocExtractResult(ctx, extractResult); err != nil {
		j.BookState.TocExtractDone = true
		return fmt.Errorf("failed to save ToC extract result: %w", err)
	}

	j.BookState.TocExtractDone = true
	return nil
}

// loadTocPages loads the ToC page content for extraction.
func (j *Job) loadTocPages(ctx context.Context) ([]extract_toc.ToCPage, error) {
	logger := svcctx.LoggerFrom(ctx)

	if j.BookState.TocStartPage == 0 || j.BookState.TocEndPage == 0 {
		return nil, fmt.Errorf("ToC page range not set")
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	// Build page filter - use _in for range or _eq for single page
	var pageFilter string
	if j.BookState.TocStartPage == j.BookState.TocEndPage {
		pageFilter = fmt.Sprintf("page_num: {_eq: %d}", j.BookState.TocStartPage)
	} else {
		// Build array of page numbers for _in filter
		var pages []string
		for p := j.BookState.TocStartPage; p <= j.BookState.TocEndPage; p++ {
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
	}`, j.BookID, pageFilter)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawPages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, fmt.Errorf("no pages found in response")
	}

	if logger != nil {
		logger.Debug("loadTocPages query result", "raw_pages_count", len(rawPages))
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

// loadTocStructureSummary loads the structure summary from the ToC finder.
func (j *Job) loadTocStructureSummary(ctx context.Context) (*extract_toc.StructureSummary, error) {
	if j.TocDocID == "" {
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
	}`, j.TocDocID)

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

// saveTocExtractResult saves the ToC extraction result to DefraDB.
// This operation is idempotent - it deletes existing entries before creating new ones.
func (j *Job) saveTocExtractResult(ctx context.Context, result *extract_toc.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Delete existing entries for this ToC (makes operation idempotent for retries)
	if err := j.deleteExistingTocEntries(ctx); err != nil {
		return fmt.Errorf("failed to delete existing ToC entries: %w", err)
	}

	// Create TocEntry records for each entry
	// Fire-and-forget - sink batches these creates
	for i, entry := range result.Entries {
		entryData := map[string]any{
			"toc_id":     j.TocDocID,
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

	// Mark extraction complete - fire-and-forget
	sink.Send(defra.WriteOp{
		Collection: "ToC",
		DocID:      j.TocDocID,
		Document: map[string]any{
			"extract_complete": true,
		},
		Op: defra.OpUpdate,
	})
	return nil
}

// deleteExistingTocEntries deletes any existing TocEntry records for this ToC.
func (j *Job) deleteExistingTocEntries(ctx context.Context) error {
	if j.TocDocID == "" {
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
	}`, j.TocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		return nil // No existing entries
	}

	// Delete each entry synchronously to ensure ordering before creates
	// (creates follow immediately after this function returns)
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
