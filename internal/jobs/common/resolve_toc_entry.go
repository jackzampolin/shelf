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

// TocEntryResolutionSpec is one operator-verified entry-to-page decision in a
// batch. Batching prevents a repair cohort from cancelling and recreating the
// process-book job once per entry.
type TocEntryResolutionSpec struct {
	EntryDocID  string
	PageNum     int
	Title       string
	Reason      string
	AllowRelink bool
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

// ResolveTocEntries applies a source-verified repair cohort with one downstream
// reset and one pending-entry reload. Every item is validated before the first
// durable mutation, including duplicate entry IDs and cross-ToC input.
func ResolveTocEntries(ctx context.Context, book *BookState, specs []TocEntryResolutionSpec) ([]TocEntryResolutionResult, int, error) {
	if len(specs) == 0 {
		return nil, 0, fmt.Errorf("at least one ToC entry resolution is required")
	}
	if len(specs) > 100 {
		return nil, 0, fmt.Errorf("ToC entry resolution batch exceeds limit of 100")
	}

	type validatedResolution struct {
		spec      TocEntryResolutionSpec
		repair    *TocEntryRepairResult
		pageDocID string
	}
	validated := make([]validatedResolution, 0, len(specs))
	seen := make(map[string]struct{}, len(specs))
	tocDocID := ""
	for _, spec := range specs {
		entryDocID := strings.TrimSpace(spec.EntryDocID)
		if _, duplicate := seen[entryDocID]; duplicate {
			return nil, 0, fmt.Errorf("duplicate ToC entry %q in resolution batch", entryDocID)
		}
		seen[entryDocID] = struct{}{}
		repair, pageDocID, err := validateTocEntryResolution(ctx, book, entryDocID, spec.PageNum, spec.Reason, spec.AllowRelink)
		if err != nil {
			return nil, 0, fmt.Errorf("validate ToC entry %s: %w", entryDocID, err)
		}
		if tocDocID == "" {
			tocDocID = repair.TocDocID
		} else if repair.TocDocID != tocDocID {
			return nil, 0, fmt.Errorf("resolution batch spans multiple ToCs")
		}
		spec.EntryDocID = entryDocID
		validated = append(validated, validatedResolution{spec: spec, repair: repair, pageDocID: pageDocID})
	}

	if err := ResetFrom(ctx, book, tocDocID, ResetTocFinalize); err != nil {
		return nil, 0, fmt.Errorf("reset downstream of ToC entry resolution batch: %w", err)
	}
	for _, item := range validated {
		if err := book.DeleteAgentStateByKeys(ctx, AgentTypeTocEntryFinder, item.spec.EntryDocID); err != nil {
			return nil, 0, fmt.Errorf("delete stale ToC entry agent state %s: %w", item.spec.EntryDocID, err)
		}
	}

	results := make([]TocEntryResolutionResult, 0, len(validated))
	for _, item := range validated {
		reason := strings.TrimSpace(item.spec.Reason)
		update := map[string]any{
			"_actual_pageID":        item.pageDocID,
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
		title := item.repair.Title
		if override := strings.TrimSpace(item.spec.Title); override != "" {
			update["title"] = override
			title = override
		}
		writeResult, err := book.getStore(ctx).UpdateWithVersion(ctx, "TocEntry", item.spec.EntryDocID, update)
		if err != nil {
			return nil, 0, fmt.Errorf("persist ToC entry page resolution %s: %w", item.spec.EntryDocID, err)
		}
		results = append(results, TocEntryResolutionResult{
			TocDocID: tocDocID, EntryDocID: item.spec.EntryDocID,
			Title: title, SortOrder: item.repair.SortOrder,
			PageNum: item.spec.PageNum, Reason: reason, CID: writeResult.CID,
		})
	}

	pendingCount, err := reopenTocLinkAfterOperatorResolution(ctx, book, tocDocID)
	if err != nil {
		return nil, 0, err
	}
	for i := range results {
		results[i].PendingCount = pendingCount
	}
	return results, pendingCount, nil
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
