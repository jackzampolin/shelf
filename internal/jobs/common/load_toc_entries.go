package common

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadTocEntries loads all TocEntry records for a ToC that haven't been linked yet.
// Returns entries that don't have an actual_page set.
func LoadTocEntries(ctx context.Context, tocDocID string) ([]*toc_entry_finder.TocEntry, error) {
	logger := svcctx.LoggerFrom(ctx)

	if tocDocID == "" {
		if logger != nil {
			logger.Warn("skipping ToC entry load: empty tocDocID")
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
		TocEntry(filter: {_tocID: {_eq: "%s"}}, order: {sort_order: ASC}) {
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
			logger.Error("ToC entry query failed", "error", err)
		}
		return nil, err
	}
	if logger != nil {
		logger.Debug("ToC entry query response received",
			"response_fields", len(resp.Data),
			"has_toc_entry", resp.Data["TocEntry"] != nil)
	}

	rawEntries, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		if logger != nil {
			logger.Warn("ToC entry query returned unexpected type", "type", fmt.Sprintf("%T", resp.Data["TocEntry"]))
		}
		return nil, nil // No entries
	}

	if logger != nil {
		logger.Debug("loaded raw ToC entries", "raw_entries", len(rawEntries))
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

func loadTocEntriesViaStore(ctx context.Context, store StateStore, tocDocID string) ([]*toc_entry_finder.TocEntry, error) {
	if tocDocID == "" {
		return nil, nil
	}
	if err := defra.ValidateID(tocDocID); err != nil {
		return nil, fmt.Errorf("invalid ToC doc ID: %w", err)
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {_tocID: {_eq: "%s"}}) {
			_docID
			entry_number
			title
			level
			level_name
			printed_page_number
			sort_order
			_actual_pageID
		}
	}`, tocDocID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	rawEntries, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		return nil, nil
	}

	entries := make([]*toc_entry_finder.TocEntry, 0, len(rawEntries))
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}
		if linkedID, ok := entry["_actual_pageID"].(string); ok && linkedID != "" {
			continue
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
		te.Level = numericToInt(entry["level"])
		if levelName, ok := entry["level_name"].(string); ok {
			te.LevelName = levelName
		}
		if printedPage, ok := entry["printed_page_number"].(string); ok {
			te.PrintedPageNumber = printedPage
		}
		te.SortOrder = numericToInt(entry["sort_order"])

		if te.DocID != "" {
			entries = append(entries, te)
		}
	}

	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].SortOrder == entries[j].SortOrder {
			return entries[i].DocID < entries[j].DocID
		}
		return entries[i].SortOrder < entries[j].SortOrder
	})

	return entries, nil
}

func numericToInt(v any) int {
	switch n := v.(type) {
	case int:
		return n
	case int32:
		return int(n)
	case int64:
		return int(n)
	case float32:
		return int(n)
	case float64:
		return int(n)
	case json.Number:
		i, _ := n.Int64()
		return int(i)
	default:
		return 0
	}
}
