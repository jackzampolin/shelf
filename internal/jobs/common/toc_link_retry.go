package common

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// PersistTocEntryLinkState records a per-entry retry or terminal skip before
// another agent is launched or the entry is counted as resolved.
func PersistTocEntryLinkState(ctx context.Context, book *BookState, entryDocID string, retries int, failed bool, reason string) error {
	if book == nil {
		return fmt.Errorf("book state is required")
	}
	if err := defra.ValidateID(entryDocID); err != nil {
		return fmt.Errorf("invalid entry doc ID: %w", err)
	}
	if retries < 0 {
		return fmt.Errorf("link retries must be non-negative")
	}
	reason = strings.TrimSpace(reason)
	update := map[string]any{
		"link_retries":        retries,
		"link_failed":         failed,
		"link_failure_reason": reason,
		"link_failed_at":      nil,
	}
	if failed {
		update["link_failed_at"] = time.Now().UTC().Format(time.RFC3339)
	}
	op := defra.WriteOp{
		Collection: "TocEntry",
		DocID:      entryDocID,
		Document:   update,
		Op:         defra.OpUpdate,
		Source:     "PersistTocEntryLinkState",
	}
	if book.Store != nil {
		_, err := book.Store.SendSync(ctx, op)
		return err
	}
	return SendToSinkSync(ctx, op)
}
