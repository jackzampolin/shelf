package common

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
)

// maxConcurrentTocWrites limits concurrent ToC entry DB writes.
const maxConcurrentTocWrites = 5

// tocEntryResult holds the result of a ToC entry persist operation.
type tocEntryResult struct {
	index int
	docID string
	cid   string
	err   error
}

// PersistTocRecord creates the initial ToC record and sets b.tocDocID. Returns DocID.
func (b *BookState) PersistTocRecord(ctx context.Context, doc map[string]any) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		Document:   doc,
		Op:         defra.OpCreate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.tocDocID = result.DocID
	b.tocCID = result.CID
	b.trackCIDLocked("ToC", result.DocID, result.CID)
	b.mu.Unlock()

	return result.DocID, nil
}

// PersistTocFinderResult saves finder result to ToC record.
// Updates b.tocFound, b.tocStartPage, b.tocEndPage.
func (b *BookState) PersistTocFinderResult(ctx context.Context, found bool, startPage, endPage int, fields map[string]any) (string, error) {
	tocDocID := b.TocDocID()
	if tocDocID == "" {
		return "", fmt.Errorf("no ToC doc ID")
	}

	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "ToC",
		DocID:      tocDocID,
		Document:   fields,
		Op:         defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.tocFound = found
	b.tocStartPage = startPage
	b.tocEndPage = endPage
	b.tocCID = result.CID
	b.trackCIDLocked("ToC", tocDocID, result.CID)
	b.mu.Unlock()

	return result.CID, nil
}

// PersistTocEntries upserts extracted TocEntry records. Updates entries with DocIDs.
// Uses bounded concurrent goroutines for performance.
// Only updates memory on full success to maintain consistency.
func (b *BookState) PersistTocEntries(ctx context.Context, tocDocID string, entries []map[string]any, uniqueKeys []string) error {
	if len(entries) == 0 {
		return nil
	}
	if len(entries) != len(uniqueKeys) {
		return fmt.Errorf("entries and uniqueKeys length mismatch: %d vs %d", len(entries), len(uniqueKeys))
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	results := make(chan tocEntryResult, len(entries))
	sem := make(chan struct{}, maxConcurrentTocWrites)
	var wg sync.WaitGroup

	for i, entry := range entries {
		wg.Add(1)
		go func(idx int, doc map[string]any, uniqueKey string) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results <- tocEntryResult{index: idx, err: fmt.Errorf("panic at index %d: %v", idx, r)}
				}
			}()

			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				results <- tocEntryResult{index: idx, err: ctx.Err()}
				return
			}

			// Make a copy of doc to avoid mutating caller's map
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

			res, err := store.UpsertWithVersion(ctx, "TocEntry", filter, createInput, updateInput)
			if err != nil {
				results <- tocEntryResult{index: idx, err: fmt.Errorf("entry %d: %w", idx, err)}
				return
			}

			results <- tocEntryResult{index: idx, docID: res.DocID, cid: res.CID}
		}(i, entry, uniqueKeys[i])
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	// Collect all results and errors
	resultSlice := make([]tocEntryResult, len(entries))
	var errors []string
	for r := range results {
		if r.err != nil {
			errors = append(errors, r.err.Error())
		}
		resultSlice[r.index] = r
	}

	// If any errors, return aggregated error without updating entries
	if len(errors) > 0 {
		return fmt.Errorf("failed to persist %d ToC entries: %s", len(errors), strings.Join(errors, "; "))
	}

	// All succeeded - update entries and memory
	b.mu.Lock()
	for i, r := range resultSlice {
		if r.docID != "" {
			entries[i]["_docID"] = r.docID
			b.trackCIDLocked("TocEntry", r.docID, r.cid)
		}
	}
	b.mu.Unlock()

	return nil
}

// PersistTocEntryLink updates a TocEntry's actual_page link.
// Updates matching entry in b.linkedEntries.
func (b *BookState) PersistTocEntryLink(ctx context.Context, entryDocID string, actualPageDocID string, actualPage int) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.UpdateWithVersion(ctx, "TocEntry", entryDocID, map[string]any{
		"actual_page_id": actualPageDocID,
	})
	if err != nil {
		return "", err
	}

	// Update memory only after DB success
	b.mu.Lock()
	b.trackCIDLocked("TocEntry", entryDocID, result.CID)
	for _, entry := range b.linkedEntries {
		if entry.DocID == entryDocID {
			entry.ActualPage = &actualPage
			entry.ActualPageDocID = actualPageDocID
			break
		}
	}
	b.mu.Unlock()

	return result.CID, nil
}

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
	if pageID, ok := doc["actual_page_id"].(string); ok {
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

// DeleteAllTocEntries deletes all TocEntry records for a ToC. Clears b.tocEntries and b.linkedEntries.
func (b *BookState) DeleteAllTocEntries(ctx context.Context, tocDocID string) error {
	if tocDocID == "" {
		b.mu.Lock()
		b.tocEntries = nil
		b.linkedEntries = nil
		b.mu.Unlock()
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query ToC entries: %w", err)
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		b.mu.Lock()
		b.tocEntries = nil
		b.linkedEntries = nil
		b.mu.Unlock()
		return nil
	}

	var ops []defra.WriteOp
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	if len(ops) > 0 {
		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to delete ToC entries: %w", err)
		}

		// Check individual results
		var errors []string
		for i, r := range results {
			if r.Err != nil {
				errors = append(errors, fmt.Sprintf("entry %s: %v", ops[i].DocID, r.Err))
			}
		}
		if len(errors) > 0 {
			return fmt.Errorf("failed to delete %d ToC entries: %s", len(errors), strings.Join(errors, "; "))
		}
	}

	// Clear memory only after all deletes succeed
	b.mu.Lock()
	b.tocEntries = nil
	b.linkedEntries = nil
	b.mu.Unlock()

	return nil
}

// ClearAllTocEntryLinks clears actual_page links from all TocEntries. Clears b.linkedEntries.
func (b *BookState) ClearAllTocEntryLinks(ctx context.Context, tocDocID string) error {
	if tocDocID == "" {
		b.mu.Lock()
		b.linkedEntries = nil
		b.mu.Unlock()
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query ToC entries: %w", err)
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		b.mu.Lock()
		b.linkedEntries = nil
		b.mu.Unlock()
		return nil
	}

	var ops []defra.WriteOp
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Document:   map[string]any{"actual_page_id": nil},
			Op:         defra.OpUpdate,
		})
	}

	if len(ops) > 0 {
		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to clear ToC entry links: %w", err)
		}

		// Check individual results
		var errors []string
		for i, r := range results {
			if r.Err != nil {
				errors = append(errors, fmt.Sprintf("entry %s: %v", ops[i].DocID, r.Err))
			}
		}
		if len(errors) > 0 {
			return fmt.Errorf("failed to clear %d ToC entry links: %s", len(errors), strings.Join(errors, "; "))
		}
	}

	// Clear memory only after all updates succeed
	b.mu.Lock()
	b.linkedEntries = nil
	b.mu.Unlock()

	return nil
}

// PersistTocExtractComplete marks ToC extraction as complete on the ToC record.
func (b *BookState) PersistTocExtractComplete(ctx context.Context, tocDocID string) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.UpdateWithVersion(ctx, "ToC", tocDocID, map[string]any{
		"extract_complete": true,
		"extract_started":  false,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.tocCID = result.CID
	b.trackCIDLocked("ToC", tocDocID, result.CID)
	b.mu.Unlock()

	return result.CID, nil
}
