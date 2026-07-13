package common

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// TocEntryRepairResult describes a surgical retry of one unlinked ToC entry.
// Existing successful links are deliberately preserved.
type TocEntryRepairResult struct {
	TocDocID   string
	EntryDocID string
	Title      string
	SortOrder  int
	Reason     string
	CID        string
}

// ValidateTocEntryRepair verifies that entryDocID is an unlinked entry owned by
// this book's ToC. Linked entries require a different, explicit relink workflow
// so a repair cannot erase a known-good result by accident.
func ValidateTocEntryRepair(ctx context.Context, book *BookState, entryDocID, reason string) (*TocEntryRepairResult, error) {
	return validateTocEntryTarget(ctx, book, entryDocID, reason, false)
}

// validateTocEntryTarget loads an entry owned by the book. allowLinked is only
// used by the explicit operator relink workflow; ordinary repair remains
// fail-safe and refuses to touch successful links.
func validateTocEntryTarget(ctx context.Context, book *BookState, entryDocID, reason string, allowLinked bool) (*TocEntryRepairResult, error) {
	if book == nil {
		return nil, fmt.Errorf("book state is required")
	}
	tocDocID := book.TocDocID()
	if tocDocID == "" {
		return nil, fmt.Errorf("book has no ToC record")
	}
	if err := defra.ValidateID(entryDocID); err != nil {
		return nil, fmt.Errorf("invalid ToC entry ID: %w", err)
	}
	if strings.TrimSpace(reason) == "" {
		return nil, fmt.Errorf("repair reason is required")
	}

	store := book.getStore(ctx)
	if store == nil {
		return nil, fmt.Errorf("no store available")
	}
	query := fmt.Sprintf(`{
		TocEntry(filter: {_docID: {_eq: %q}, _tocID: {_eq: %q}}) {
			_docID
			title
			sort_order
			actual_page {
				_docID
			}
		}
	}`, entryDocID, tocDocID)
	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("query ToC entry: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query ToC entry: %s", errMsg)
	}
	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) != 1 {
		return nil, fmt.Errorf("ToC entry %s was not found in book %s", entryDocID, book.BookID)
	}
	entry, ok := entries[0].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("ToC entry %s has an invalid record", entryDocID)
	}
	if linkedID, _ := entry["_actual_pageID"].(string); linkedID != "" && !allowLinked {
		return nil, fmt.Errorf("ToC entry %s is already linked; refusing to erase a successful link", entryDocID)
	}
	if actualPage, ok := entry["actual_page"].(map[string]any); ok {
		if linkedID, _ := actualPage["_docID"].(string); linkedID != "" && !allowLinked {
			return nil, fmt.Errorf("ToC entry %s is already linked; refusing to erase a successful link", entryDocID)
		}
	}

	title, _ := entry["title"].(string)
	return &TocEntryRepairResult{
		TocDocID:   tocDocID,
		EntryDocID: entryDocID,
		Title:      title,
		SortOrder:  numericToInt(entry["sort_order"]),
		Reason:     strings.TrimSpace(reason),
	}, nil
}

// RepairTocEntry resets only one unlinked entry's retry budget and stale agent
// state. It invalidates finalize/structure artifacts, but preserves every
// successful TocEntry->Page link. The caller must stop an active job first and
// submit a replacement process-book job afterward.
func RepairTocEntry(ctx context.Context, book *BookState, entryDocID, reason string) (*TocEntryRepairResult, error) {
	result, err := ValidateTocEntryRepair(ctx, book, entryDocID, reason)
	if err != nil {
		return nil, err
	}

	// A prior finalize or structure may have accepted this entry as skipped.
	// Reset those artifacts before making the entry pending again.
	if err := ResetFrom(ctx, book, result.TocDocID, ResetTocFinalize); err != nil {
		return nil, fmt.Errorf("reset downstream of ToC entry repair: %w", err)
	}
	if err := book.DeleteAgentStateByKeys(ctx, AgentTypeTocEntryFinder, entryDocID); err != nil {
		return nil, fmt.Errorf("delete stale ToC entry agent state: %w", err)
	}

	store := book.getStore(ctx)
	update := map[string]any{
		"link_retries":          0,
		"link_failed":           false,
		"link_failure_reason":   nil,
		"link_failed_at":        nil,
		"link_excluded":         false,
		"link_exclusion_reason": nil,
		"link_excluded_at":      nil,
		"link_repair_reason":    result.Reason,
		"link_repaired_at":      time.Now().UTC().Format(time.RFC3339),
	}
	writeResult, err := store.UpdateWithVersion(ctx, "TocEntry", entryDocID, update)
	if err != nil {
		return nil, fmt.Errorf("reset ToC entry link state: %w", err)
	}
	result.CID = writeResult.CID

	// Reopen the aggregate link stage without invoking its reset hook, which
	// would clear every successful entry link.
	book.SetOpState(OpTocLink, false, false, false, 0)
	if err := book.PersistOpState(ctx, OpTocLink); err != nil {
		return nil, fmt.Errorf("reopen ToC link operation: %w", err)
	}
	pending, err := reloadTocEntriesAfterLinkReset(ctx, book, result.TocDocID)
	if err != nil {
		return nil, fmt.Errorf("reload pending ToC entries: %w", err)
	}
	book.SetTocEntries(pending)
	book.SetTocLinkProgress(len(pending), 0)
	if err := book.PersistTocLinkProgress(ctx); err != nil {
		return nil, fmt.Errorf("reset ToC link progress: %w", err)
	}

	return result, nil
}
