package common

import (
	"context"
	"fmt"
	"strings"
	"time"
)

// TocEntryExclusionResult records an explicit operator decision that a ToC
// item is absent from the source artifact and should not become a chapter.
type TocEntryExclusionResult struct {
	TocDocID     string
	EntryDocID   string
	Title        string
	SortOrder    int
	Reason       string
	CID          string
	PendingCount int
}

func ValidateTocEntryExclusion(ctx context.Context, book *BookState, entryDocID, reason string) error {
	_, err := validateTocEntryTarget(ctx, book, entryDocID, reason, false)
	return err
}

// ExcludeTocEntry marks one unlinked, non-content entry explicitly excluded,
// with durable provenance. Unlike retry exhaustion, exclusion is an operator
// resolution and may allow the aggregate link stage to continue.
func ExcludeTocEntry(ctx context.Context, book *BookState, entryDocID, reason string) (*TocEntryExclusionResult, error) {
	target, err := validateTocEntryTarget(ctx, book, entryDocID, reason, false)
	if err != nil {
		return nil, err
	}
	if err := ResetFrom(ctx, book, target.TocDocID, ResetTocFinalize); err != nil {
		return nil, fmt.Errorf("reset downstream of ToC entry exclusion: %w", err)
	}
	if err := book.DeleteAgentStateByKeys(ctx, AgentTypeTocEntryFinder, entryDocID); err != nil {
		return nil, fmt.Errorf("delete stale ToC entry agent state: %w", err)
	}

	reason = strings.TrimSpace(reason)
	writeResult, err := book.getStore(ctx).UpdateWithVersion(ctx, "TocEntry", entryDocID, map[string]any{
		"link_retries":          0,
		"link_failed":           false,
		"link_failure_reason":   nil,
		"link_failed_at":        nil,
		"link_excluded":         true,
		"link_exclusion_reason": reason,
		"link_excluded_at":      time.Now().UTC().Format(time.RFC3339),
	})
	if err != nil {
		return nil, fmt.Errorf("persist ToC entry exclusion: %w", err)
	}
	pendingCount, err := reopenTocLinkAfterOperatorResolution(ctx, book, target.TocDocID)
	if err != nil {
		return nil, err
	}

	return &TocEntryExclusionResult{
		TocDocID: target.TocDocID, EntryDocID: entryDocID,
		Title: target.Title, SortOrder: target.SortOrder,
		Reason: reason, CID: writeResult.CID, PendingCount: pendingCount,
	}, nil
}
