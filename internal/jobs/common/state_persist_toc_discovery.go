package common

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

// PersistDiscoveredEntry upserts a discovered TocEntry. Adds to b.linkedEntries.
func (b *BookState) PersistDiscoveredEntry(ctx context.Context, tocDocID string, doc map[string]any, uniqueKey string) (defra.WriteResult, error) {
	store := b.getStore(ctx)
	if store == nil {
		return defra.WriteResult{}, fmt.Errorf("no store available")
	}

	// Make copies to avoid mutating caller's map
	createInput := make(map[string]any, len(doc)+1)
	for k, v := range doc {
		createInput[k] = v
	}
	createInput["unique_key"] = uniqueKey

	updateInput := make(map[string]any, len(doc))
	for k, v := range doc {
		updateInput[k] = v
	}

	filter := map[string]any{"unique_key": uniqueKey}

	result, err := store.UpsertWithVersion(ctx, "TocEntry", filter, createInput, updateInput)
	if err != nil {
		return result, err
	}

	// Build LinkedTocEntry from doc
	entry := &LinkedTocEntry{
		DocID:  result.DocID,
		Source: "discovered",
	}
	if title, ok := doc["title"].(string); ok {
		entry.Title = title
	}
	if num, ok := doc["entry_number"].(string); ok {
		entry.EntryNumber = num
	}
	if level, ok := doc["level"].(int); ok {
		entry.Level = level
	}
	if levelName, ok := doc["level_name"].(string); ok {
		entry.LevelName = levelName
	}
	if sortOrder, ok := doc["sort_order"].(int); ok {
		entry.SortOrder = sortOrder
	}
	if pageID, ok := doc["_actual_pageID"].(string); ok {
		entry.ActualPageDocID = pageID
	}

	b.mu.Lock()
	b.trackCIDLocked("TocEntry", result.DocID, result.CID)
	b.linkedEntries = append(b.linkedEntries, entry)
	b.mu.Unlock()

	return result, nil
}

// PersistGapFix applies a gap fix (add_entry or correct_entry). Updates b.linkedEntries.
func (b *BookState) PersistGapFix(ctx context.Context, tocDocID string, fixType string, doc map[string]any, uniqueKey string) (defra.WriteResult, error) {
	store := b.getStore(ctx)
	if store == nil {
		return defra.WriteResult{}, fmt.Errorf("no store available")
	}

	// Make copies to avoid mutating caller's map
	createInput := make(map[string]any, len(doc)+1)
	for k, v := range doc {
		createInput[k] = v
	}
	createInput["unique_key"] = uniqueKey

	updateInput := make(map[string]any, len(doc))
	for k, v := range doc {
		updateInput[k] = v
	}

	filter := map[string]any{"unique_key": uniqueKey}

	result, err := store.UpsertWithVersion(ctx, "TocEntry", filter, createInput, updateInput)
	if err != nil {
		return result, err
	}

	// Update memory based on fix type
	b.mu.Lock()
	b.trackCIDLocked("TocEntry", result.DocID, result.CID)

	if fixType == "add_entry" {
		entry := &LinkedTocEntry{
			DocID:  result.DocID,
			Source: "discovered",
		}
		if title, ok := doc["title"].(string); ok {
			entry.Title = title
		}
		if num, ok := doc["entry_number"].(string); ok {
			entry.EntryNumber = num
		}
		if level, ok := doc["level"].(int); ok {
			entry.Level = level
		}
		if levelName, ok := doc["level_name"].(string); ok {
			entry.LevelName = levelName
		}
		if sortOrder, ok := doc["sort_order"].(int); ok {
			entry.SortOrder = sortOrder
		}
		b.linkedEntries = append(b.linkedEntries, entry)
	} else if fixType == "correct_entry" {
		for _, entry := range b.linkedEntries {
			if entry.DocID == result.DocID {
				if title, ok := doc["title"].(string); ok {
					entry.Title = title
				}
				if num, ok := doc["entry_number"].(string); ok {
					entry.EntryNumber = num
				}
				break
			}
		}
	}
	b.mu.Unlock()

	return result, nil
}

// sortUpdate tracks a pending sort order change.
type sortUpdate struct {
	entry    *LinkedTocEntry
	newOrder int
}

// PersistEntryResort re-sorts all entries by actual_page and batch-updates sort_order.
// Updates b.linkedEntries with new sort orders only after DB success.
func (b *BookState) PersistEntryResort(ctx context.Context, tocDocID string) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Get current entries
	entries := b.GetLinkedEntries()
	if len(entries) == 0 {
		return nil
	}

	// Sort by actual_page (nil pages go to end)
	sort.SliceStable(entries, func(i, j int) bool {
		if entries[i].ActualPage == nil && entries[j].ActualPage == nil {
			return entries[i].SortOrder < entries[j].SortOrder
		}
		if entries[i].ActualPage == nil {
			return false
		}
		if entries[j].ActualPage == nil {
			return true
		}
		return *entries[i].ActualPage < *entries[j].ActualPage
	})

	// Build update ops for entries whose sort_order changed - DON'T update memory yet
	var ops []defra.WriteOp
	var updates []sortUpdate
	for newOrder, entry := range entries {
		if entry.SortOrder != newOrder {
			ops = append(ops, defra.WriteOp{
				Collection: "TocEntry",
				DocID:      entry.DocID,
				Document:   map[string]any{"sort_order": newOrder},
				Op:         defra.OpUpdate,
			})
			updates = append(updates, sortUpdate{entry: entry, newOrder: newOrder})
		}
	}

	if len(ops) > 0 {
		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to update sort orders: %w", err)
		}

		// Check individual results
		var errors []string
		for i, r := range results {
			if r.Err != nil {
				errors = append(errors, fmt.Sprintf("entry %s: %v", ops[i].DocID, r.Err))
			}
		}
		if len(errors) > 0 {
			return fmt.Errorf("failed to update %d sort orders: %s", len(errors), strings.Join(errors, "; "))
		}

		// Only update memory after DB success
		for _, u := range updates {
			u.entry.SortOrder = u.newOrder
		}
	}

	// Update memory with sorted entries
	b.mu.Lock()
	b.linkedEntries = entries
	b.mu.Unlock()

	return nil
}
