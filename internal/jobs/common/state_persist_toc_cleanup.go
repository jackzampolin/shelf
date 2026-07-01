package common

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

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
		TocEntry(filter: {_tocID: {_eq: "%s"}}) {
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
		TocEntry(filter: {_tocID: {_eq: "%s"}}) {
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
			Document:   map[string]any{"_actual_pageID": nil},
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
