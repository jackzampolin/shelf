package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// deleteAgentStatesForTypeViaStore deletes agent states using the StateStore interface.
// This enables reset operations to work without a DefraDB client in context.
func deleteAgentStatesForTypeViaStore(ctx context.Context, store StateStore, bookID, agentType string) error {
	query := fmt.Sprintf(`{
		AgentState(filter: {_bookID: {_eq: "%s"}, agent_type: {_eq: "%s"}}) {
			_docID
		}
	}`, bookID, agentType)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query agent states: %w", err)
	}

	states, ok := resp.Data["AgentState"].([]any)
	if !ok || len(states) == 0 {
		return nil
	}

	ops := make([]defra.WriteOp, 0, len(states))
	for _, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "AgentState",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	if len(ops) == 0 {
		return nil
	}

	results, err := store.SendManySync(ctx, ops)
	if err != nil {
		return fmt.Errorf("failed to delete agent states: %w", err)
	}
	for _, result := range results {
		if result.Err != nil {
			return fmt.Errorf("failed to delete agent state %s: %w", result.DocID, result.Err)
		}
	}

	return nil
}

// deleteTocEntries deletes all ToC entries for a ToC.
func deleteTocEntries(ctx context.Context, tocDocID string) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {_tocID: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query ToC entries for deletion: %w", err)
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Collect all ops for batch processing
	var ops []defra.WriteOp
	var skipCount int
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected ToC entry data type during deletion", "type", fmt.Sprintf("%T", e))
			}
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during ToC entry deletion", "entry_data", entry)
			}
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	// Send all ops in batch
	var failCount int
	if len(ops) > 0 {
		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to batch delete ToC entries: %w", err)
		}
		for _, r := range results {
			if r.Err != nil {
				failCount++
				if logger != nil {
					logger.Error("failed to delete ToC entry", "doc_id", r.DocID, "error", r.Err)
				}
			}
		}
	}

	deleteCount := len(ops) - failCount
	if logger != nil {
		logger.Debug("ToC entries deletion completed", "delete_count", deleteCount, "skipped", skipCount, "failed", failCount, "toc_id", tocDocID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("ToC entry deletion had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}

// clearTocEntryLinks clears actual_page links from ToC entries.
func clearTocEntryLinks(ctx context.Context, tocDocID string) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {_tocID: {_eq: "%s"}}) {
			_docID
		}
	}`, tocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query ToC entries for link clearing: %w", err)
	}

	entries, ok := resp.Data["TocEntry"].([]any)
	if !ok || len(entries) == 0 {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	var clearCount, skipCount, failCount int
	ops := make([]defra.WriteOp, 0, len(entries))
	for _, e := range entries {
		entry, ok := e.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected ToC entry data type during link clearing", "type", fmt.Sprintf("%T", e))
			}
			continue
		}
		docID, ok := entry["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during ToC entry link clearing", "entry_data", entry)
			}
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Document: map[string]any{
				"_actual_pageID":      nil,
				"link_retries":        0,
				"link_failed":         false,
				"link_failure_reason": nil,
				"link_failed_at":      nil,
			},
			Op: defra.OpUpdate,
		})
	}

	if len(ops) > 0 {
		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to batch clear ToC entry links: %w", err)
		}
		clearCount = len(ops)
		for _, result := range results {
			if result.Err != nil {
				failCount++
				clearCount--
				if logger != nil {
					logger.Error("failed to clear ToC entry link", "doc_id", result.DocID, "error", result.Err)
				}
			}
		}
	}

	if logger != nil {
		logger.Debug("ToC entry links clearing completed", "clear_count", clearCount, "skipped", skipCount, "failed", failCount, "toc_id", tocDocID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("ToC entry link clearing had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}
