package common

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strconv"
	"strings"

	"github.com/google/uuid"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

var (
	// Some structured-output models occasionally serialize a visually indented
	// run of ToC rows as one title. Requiring three complete "title, page."
	// anchors makes this distinct from ordinary punctuation in a title.
	collapsedTocRowPattern = regexp.MustCompile(`(?s)(.*?),\s*([0-9]{1,5})\.`)
	// In the same failure shape, top-level page anchors are commonly emitted as
	// part of the title ("Introduction: I") rather than in the page field.
	colonPageAnchorPattern = regexp.MustCompile(`(?s)^(.+\S)\s*:\s*([0-9]{1,5}|[IVXLCDMivxlcdm]+)\.?$`)
)

// CreateTocExtractWorkUnit creates a ToC extraction work unit.
// Returns nil if no ToC pages are available.
// The caller is responsible for registering the work unit with their tracker.
func CreateTocExtractWorkUnit(ctx context.Context, jc JobContext, tocDocID string) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	logger := svcctx.LoggerFrom(ctx)

	// Get ToC page range
	tocStartPage, tocEndPage := book.GetTocPageRange()

	// Load ToC pages via read-through BookState.
	tocPages := LoadTocPagesFromState(ctx, book, tocStartPage, tocEndPage)

	if len(tocPages) == 0 {
		if logger != nil {
			logger.Warn("no ToC pages found in state or DB",
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
	unit.Priority = jobs.PriorityForStage("toc_extract")

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     "toc",
		ItemKey:   "toc_extract",
		PromptKey: extract_toc.SystemPromptKey,
		PromptCID: book.GetPromptCID(extract_toc.SystemPromptKey),
	}

	return unit, unitID
}

// LoadTocPagesFromState loads ToC page content via read-through cache.
// Uses BookState.GetOcrMarkdown to load from DB when needed.
func LoadTocPagesFromState(ctx context.Context, book *BookState, startPage, endPage int) []extract_toc.ToCPage {
	if startPage == 0 || endPage == 0 {
		return nil
	}

	var tocPages []extract_toc.ToCPage
	for pageNum := startPage; pageNum <= endPage; pageNum++ {
		ocrMarkdown, err := book.GetOcrMarkdown(ctx, pageNum)
		if err != nil {
			continue
		}
		if ocrMarkdown == "" {
			continue
		}

		tocPages = append(tocPages, extract_toc.ToCPage{
			PageNum: pageNum,
			OCRText: ocrMarkdown,
		})
	}

	return tocPages
}

// LoadTocStructureSummary loads the structure summary from the ToC finder.
func LoadTocStructureSummary(ctx context.Context, tocDocID string) (*extract_toc.StructureSummary, error) {
	if tocDocID == "" {
		return nil, nil
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

// SaveTocExtractResult saves the ToC extraction result to DefraDB.
// This operation is idempotent - uses upsert to create or update entries.
func SaveTocExtractResult(ctx context.Context, tocDocID string, result *extract_toc.Result) (string, error) {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return "", fmt.Errorf("defra client not in context")
	}
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return "", fmt.Errorf("defra sink not in context")
	}

	entries, normalized, err := normalizeTocExtractEntries(result.Entries)
	if err != nil {
		return "", fmt.Errorf("invalid collapsed ToC extraction: %w", err)
	}

	if logger != nil {
		logger.Debug("upserting extracted ToC entries",
			"toc_doc_id", tocDocID,
			"entry_count", len(entries),
			"model_entry_count", len(result.Entries),
			"normalized_collapsed_rows", normalized)
	}

	// Defra retains deleted document identities as tombstones. Reusing the old
	// deterministic unique_key after reset can therefore fail even though no
	// active row is queryable. Treat each extraction result as one replace-set:
	// remove any active partial attempt, then namespace all rows by a fresh
	// generation so neither tombstones nor a prior partial save can collide.
	if err := deleteTocEntries(ctx, tocDocID); err != nil {
		return "", fmt.Errorf("failed to clear previous ToC extraction rows: %w", err)
	}
	generation := uuid.NewString()

	// Upsert each TocEntry (filter by unique_key for uniqueness)
	for i, entry := range entries {
		// A generation-scoped key avoids Defra tombstone ID reuse after reset.
		uniqueKey := fmt.Sprintf("%s:%s:%d", tocDocID, generation, i)

		entryData := map[string]any{
			"_tocID":        tocDocID,
			"unique_key":    uniqueKey,
			"title":         entry.Title,
			"level":         entry.Level,
			"sort_order":    i,
			"link_retries":  0,
			"link_failed":   false,
			"link_excluded": false,
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
		if err != nil && isDefraDocIDCollision(err) {
			// A previous partial toc_extract can leave the same logical row under
			// an older unique_key. Defra derives the would-be add DocID from the
			// new input, so upsert reports an ID collision even though the stable
			// key filter found nothing. Recover by the load-bearing identity for
			// this relation: ToC + sort order.
			existingDocID, findErr := findTocEntryByIdentity(ctx, defraClient, tocDocID, i)
			if findErr != nil {
				return "", fmt.Errorf("failed to recover TocEntry %d collision: %w", i, findErr)
			}
			if existingDocID != "" {
				if logger != nil {
					logger.Warn("ToC entry upsert collided; updating existing entry by identity",
						"sort_order", i,
						"toc_doc_id", tocDocID,
						"existing_doc_id", existingDocID,
						"error", err)
				}
				_, err = defraClient.UpdateWithVersion(ctx, "TocEntry", existingDocID, entryData)
			}
		}
		if err != nil {
			if logger != nil {
				logger.Error("failed to upsert extracted ToC entry",
					"sort_order", i,
					"title", entry.Title,
					"error", err)
			}
			return "", fmt.Errorf("failed to upsert TocEntry %d: %w", i, err)
		}
	}

	if logger != nil {
		logger.Debug("upserted all extracted ToC entries",
			"toc_doc_id", tocDocID,
			"count", len(entries))
	}

	// Mark extraction complete
	writeResult, err := sink.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document: map[string]any{
			"extract_complete": true,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}
	return writeResult.CID, nil
}

// normalizeTocExtractEntries repairs one narrow, mechanically recognizable
// structured-output failure: multiple visually indented ToC rows collapsed into
// a single title. It deliberately leaves ordinary titles untouched. Once that
// failure shape is present, its companion "Title: page" top-level encoding is
// normalized as well.
func normalizeTocExtractEntries(entries []extract_toc.Entry) ([]extract_toc.Entry, int, error) {
	type normalizedEntry struct {
		entries   []extract_toc.Entry
		collapsed bool
	}

	parsed := make([]normalizedEntry, 0, len(entries))
	collapsedRows := 0
	for i, entry := range entries {
		split, collapsed, err := splitCollapsedTocEntry(entry)
		if err != nil {
			return nil, 0, fmt.Errorf("entry %d (%q): %w", i, entry.Title, err)
		}
		if collapsed {
			collapsedRows++
		}
		parsed = append(parsed, normalizedEntry{entries: split, collapsed: collapsed})
	}

	if collapsedRows == 0 {
		return append([]extract_toc.Entry(nil), entries...), 0, nil
	}

	result := make([]extract_toc.Entry, 0, len(entries)+collapsedRows*3)
	for _, item := range parsed {
		for _, entry := range item.entries {
			if !item.collapsed {
				entry = normalizeColonPageAnchor(entry)
			}
			result = append(result, entry)
		}
	}
	return result, collapsedRows, nil
}

func splitCollapsedTocEntry(entry extract_toc.Entry) ([]extract_toc.Entry, bool, error) {
	if entry.Level < 2 || entry.PrintedPageNumber != nil || entry.EntryNumber != nil {
		return []extract_toc.Entry{entry}, false, nil
	}

	matches := collapsedTocRowPattern.FindAllStringSubmatchIndex(entry.Title, -1)
	if len(matches) < 3 {
		return []extract_toc.Entry{entry}, false, nil
	}
	if strings.TrimSpace(entry.Title[:matches[0][0]]) != "" ||
		strings.TrimSpace(entry.Title[matches[len(matches)-1][1]:]) != "" {
		return nil, false, fmt.Errorf("page-anchor sequence does not cover the full title")
	}

	result := make([]extract_toc.Entry, 0, len(matches))
	previousPage := 0
	for _, match := range matches {
		title := strings.TrimSpace(entry.Title[match[2]:match[3]])
		pageText := entry.Title[match[4]:match[5]]
		page, err := strconv.Atoi(pageText)
		if err != nil || page <= previousPage || title == "" {
			return nil, false, fmt.Errorf("page anchors must have non-empty titles and strictly increase")
		}
		previousPage = page
		pageCopy := pageText
		result = append(result, extract_toc.Entry{
			Title:             title,
			Level:             entry.Level,
			LevelName:         entry.LevelName,
			PrintedPageNumber: &pageCopy,
		})
	}
	return result, true, nil
}

func normalizeColonPageAnchor(entry extract_toc.Entry) extract_toc.Entry {
	if entry.Level != 1 || entry.PrintedPageNumber != nil {
		return entry
	}
	match := colonPageAnchorPattern.FindStringSubmatch(entry.Title)
	if match == nil {
		return entry
	}
	entry.Title = strings.TrimSpace(match[1])
	page := match[2]
	entry.PrintedPageNumber = &page
	return entry
}

func isDefraDocIDCollision(err error) bool {
	if err == nil {
		return false
	}
	msg := strings.ToLower(err.Error())
	return strings.Contains(msg, "document with the given id already exists") ||
		strings.Contains(msg, "document with given id already exists")
}

func findTocEntryByIdentity(ctx context.Context, client *defra.Client, tocDocID string, sortOrder int) (string, error) {
	query := fmt.Sprintf(`{
		TocEntry(filter: {_tocID: {_eq: %q}}, limit: 5000) {
			_docID
			sort_order
			unique_key
		}
	}`, tocDocID)
	resp, err := client.Execute(ctx, query, nil)
	if err != nil {
		return "", fmt.Errorf("failed to query existing ToC entries: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return "", fmt.Errorf("failed to query existing ToC entries: %s", errMsg)
	}
	raw, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		return "", fmt.Errorf("unexpected TocEntry identity response: %+v", resp.Data)
	}
	matches := make([]string, 0, 1)
	for _, item := range raw {
		entry, ok := item.(map[string]any)
		if !ok || numericToInt(entry["sort_order"]) != sortOrder {
			continue
		}
		docID, _ := entry["_docID"].(string)
		if docID != "" {
			matches = append(matches, docID)
		}
	}
	if len(matches) > 1 {
		return "", fmt.Errorf("multiple TocEntry records matched toc=%s sort_order=%d", tocDocID, sortOrder)
	}
	if len(matches) == 1 {
		return matches[0], nil
	}
	return "", nil
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

	// Validate tocDocID to prevent GraphQL injection
	if err := defra.ValidateID(tocDocID); err != nil {
		return nil, fmt.Errorf("invalid ToC doc ID: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {_tocID: {_eq: "%s"}}, order: {sort_order: ASC}) {
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

// GetOrLoadLinkedEntries returns linked entries from cache, or loads from DB if not cached.
// This ensures LinkedEntries is only loaded once per job execution.
func GetOrLoadLinkedEntries(ctx context.Context, book *BookState, tocDocID string) ([]*LinkedTocEntry, error) {
	// Check cache first
	if book.HasLinkedEntries() {
		return book.GetLinkedEntries(), nil
	}

	// Load from DB
	entries, err := LoadLinkedEntries(ctx, tocDocID)
	if err != nil {
		return nil, err
	}

	// Cache in BookState
	book.SetLinkedEntries(entries)
	return entries, nil
}

// RefreshLinkedEntries forces a reload of linked entries from DB.
// Use this after modifications that change entry links.
func RefreshLinkedEntries(ctx context.Context, book *BookState, tocDocID string) ([]*LinkedTocEntry, error) {
	// Load from DB first - don't clear cache until load succeeds
	entries, err := LoadLinkedEntries(ctx, tocDocID)
	if err != nil {
		// Preserve existing cache on failure
		return nil, err
	}

	// Only update cache after successful load
	book.SetLinkedEntries(entries)
	return entries, nil
}

// SaveTocEntryResult updates a TocEntry with the found page link.
// Used by link_toc operations in both process_book and standalone link_toc jobs.
func SaveTocEntryResult(ctx context.Context, book *BookState, entryDocID string, result *toc_entry_finder.Result) (string, error) {
	// Validate entryDocID to prevent injection
	if err := defra.ValidateID(entryDocID); err != nil {
		return "", fmt.Errorf("invalid entry doc ID: %w", err)
	}

	store := book.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	update := map[string]any{
		"link_failed":           false,
		"link_failure_reason":   nil,
		"link_failed_at":        nil,
		"link_excluded":         false,
		"link_exclusion_reason": nil,
		"link_excluded_at":      nil,
	}

	if result.ScanPage != nil {
		// Get page doc ID from BookState
		state := book.GetPage(*result.ScanPage)
		if state != nil {
			pageDocID := state.GetPageDocID()
			if pageDocID != "" {
				update["_actual_pageID"] = pageDocID
			}
		}
	}

	if len(update) > 0 {
		writeResult, err := store.UpdateWithVersion(ctx, "TocEntry", entryDocID, update)
		if err != nil {
			return "", err
		}
		return writeResult.CID, nil
	}

	return "", nil
}
