package common

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// TocEntryResolutionResult describes an operator-verified TocEntry -> Page
// link. Existing successful links are preserved.
type TocEntryResolutionResult struct {
	TocDocID     string
	EntryDocID   string
	Title        string
	SortOrder    int
	PageNum      int
	Reason       string
	CID          string
	PendingCount int
}

// ValidateTocEntryResolution checks the entry and target page without changing
// durable state. Endpoints call this before cancelling an active job so invalid
// operator input cannot interrupt healthy work.
func ValidateTocEntryResolution(ctx context.Context, book *BookState, entryDocID string, pageNum int, reason string, allowRelink bool) error {
	_, _, err := validateTocEntryResolution(ctx, book, entryDocID, pageNum, reason, allowRelink)
	return err
}

func validateTocEntryResolution(ctx context.Context, book *BookState, entryDocID string, pageNum int, reason string, allowRelink bool) (*TocEntryRepairResult, string, error) {
	repair, err := validateTocEntryTarget(ctx, book, entryDocID, reason, allowRelink)
	if err != nil {
		return nil, "", err
	}
	if pageNum < 1 || pageNum > book.TotalPages {
		return nil, "", fmt.Errorf("page %d is outside valid range 1-%d", pageNum, book.TotalPages)
	}
	page := book.GetPage(pageNum)
	if page == nil {
		return nil, "", fmt.Errorf("page %d is missing", pageNum)
	}
	if quarantined, quarantineReason := page.OCRQuarantine(); quarantined {
		return nil, "", fmt.Errorf("page %d is OCR-quarantined: %s", pageNum, quarantineReason)
	}
	if !page.OcrResolved(book.OcrProviders) {
		return nil, "", fmt.Errorf("page %d does not have terminal OCR", pageNum)
	}
	pageDocID := page.GetPageDocID()
	if pageDocID == "" {
		return nil, "", fmt.Errorf("page %d has no durable document ID", pageNum)
	}
	return repair, pageDocID, nil
}

// ResolveTocEntry links one unlinked ToC entry to an operator-verified scan
// page, resets downstream artifacts, and reopens (or completes) the aggregate
// link stage. The caller must stop an active job before calling and submit a
// replacement process-book job afterward.
func ResolveTocEntry(ctx context.Context, book *BookState, entryDocID string, pageNum int, reason string, allowRelink bool, titleOverride string) (*TocEntryResolutionResult, error) {
	repair, pageDocID, err := validateTocEntryResolution(ctx, book, entryDocID, pageNum, reason, allowRelink)
	if err != nil {
		return nil, err
	}

	if err := ResetFrom(ctx, book, repair.TocDocID, ResetTocFinalize); err != nil {
		return nil, fmt.Errorf("reset downstream of ToC entry resolution: %w", err)
	}
	if err := book.DeleteAgentStateByKeys(ctx, AgentTypeTocEntryFinder, entryDocID); err != nil {
		return nil, fmt.Errorf("delete stale ToC entry agent state: %w", err)
	}

	reason = strings.TrimSpace(reason)
	update := map[string]any{
		"_actual_pageID":        pageDocID,
		"link_retries":          0,
		"link_failed":           false,
		"link_failure_reason":   nil,
		"link_failed_at":        nil,
		"link_excluded":         false,
		"link_exclusion_reason": nil,
		"link_excluded_at":      nil,
		"link_repair_reason":    reason,
		"link_repaired_at":      time.Now().UTC().Format(time.RFC3339),
	}
	if title := strings.TrimSpace(titleOverride); title != "" {
		update["title"] = title
		repair.Title = title
	}
	writeResult, err := book.getStore(ctx).UpdateWithVersion(ctx, "TocEntry", entryDocID, update)
	if err != nil {
		return nil, fmt.Errorf("persist ToC entry page resolution: %w", err)
	}

	pendingCount, err := reopenTocLinkAfterOperatorResolution(ctx, book, repair.TocDocID)
	if err != nil {
		return nil, err
	}

	return &TocEntryResolutionResult{
		TocDocID: repair.TocDocID, EntryDocID: entryDocID,
		Title: repair.Title, SortOrder: repair.SortOrder,
		PageNum: pageNum, Reason: reason, CID: writeResult.CID,
		PendingCount: pendingCount,
	}, nil
}

func reopenTocLinkAfterOperatorResolution(ctx context.Context, book *BookState, tocDocID string) (int, error) {
	pending, err := reloadTocEntriesAfterLinkReset(ctx, book, tocDocID)
	if err != nil {
		return 0, fmt.Errorf("reload pending ToC entries: %w", err)
	}
	book.SetTocEntries(pending)
	book.SetTocLinkProgress(len(pending), 0)
	if len(pending) == 0 {
		book.SetOpState(OpTocLink, false, true, false, 0)
	} else {
		book.SetOpState(OpTocLink, false, false, false, 0)
	}
	if err := book.PersistOpState(ctx, OpTocLink); err != nil {
		return 0, fmt.Errorf("persist reopened ToC link operation: %w", err)
	}
	if err := book.PersistTocLinkProgress(ctx); err != nil {
		return 0, fmt.Errorf("persist ToC link progress: %w", err)
	}
	return len(pending), nil
}
