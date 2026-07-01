package common

import (
	"context"
	"fmt"
	"strings"
	"sync"
)

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
		"_actual_pageID": actualPageDocID,
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
