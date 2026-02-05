package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ResetOperation identifies an operation that can be reset.
type ResetOperation string

const (
	ResetMetadata    ResetOperation = "metadata"
	ResetTocFinder   ResetOperation = "toc_finder"
	ResetTocExtract  ResetOperation = "toc_extract"
	ResetTocLink     ResetOperation = "toc_link"
	ResetTocFinalize ResetOperation = "toc_finalize"
	ResetStructure   ResetOperation = "structure"
	ResetOcr         ResetOperation = "ocr"
)

// ValidResetOperations lists all valid reset operations.
var ValidResetOperations = []ResetOperation{
	ResetMetadata,
	ResetTocFinder,
	ResetTocExtract,
	ResetTocLink,
	ResetTocFinalize,
	ResetStructure,
	ResetOcr,
}

// IsValidResetOperation checks if an operation name is valid.
func IsValidResetOperation(op string) bool {
	for _, valid := range ValidResetOperations {
		if string(valid) == op {
			return true
		}
	}
	return false
}

// ResetFrom resets an operation and all its downstream dependencies.
// This enables re-running specific stages of the pipeline.
//
// Cascade dependencies are defined in OpRegistry.CascadesTo.
// OCR is a special case handled separately (not in OpRegistry).
func ResetFrom(ctx context.Context, book *BookState, tocDocID string, op ResetOperation) error {
	// Validate IDs to prevent GraphQL injection
	if err := defra.ValidateID(book.BookID); err != nil {
		return fmt.Errorf("invalid book ID: %w", err)
	}
	if tocDocID != "" {
		if err := defra.ValidateID(tocDocID); err != nil {
			return fmt.Errorf("invalid ToC doc ID: %w", err)
		}
	}

	// Ensure tocDocID is stored on book for OpConfig.DocIDSource
	if tocDocID != "" {
		book.SetTocDocID(tocDocID)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Debug("resetting operation with cascade", "operation", op, "book_id", book.BookID)
	}

	// OCR is a special case — not in the OpRegistry
	if op == ResetOcr {
		if err := resetAllOcr(ctx, book); err != nil {
			return err
		}
		// OCR reset cascades to ToC link and downstream operations
		return resetOpWithCascade(ctx, book, tocDocID, OpTocLink)
	}

	// Standard operations use the registry
	opType := OpType(op)
	if _, ok := OpRegistry[opType]; !ok {
		return fmt.Errorf("unknown reset operation: %s", op)
	}

	return resetOpWithCascade(ctx, book, tocDocID, opType)
}

// resetOpWithCascade resets an operation and recursively resets all downstream operations.
func resetOpWithCascade(ctx context.Context, book *BookState, tocDocID string, op OpType) error {
	cfg, ok := OpRegistry[op]
	if !ok {
		return fmt.Errorf("unknown operation: %s", op)
	}

	// Reset this operation
	if err := resetOp(ctx, book, tocDocID, op); err != nil {
		return err
	}

	// Cascade to downstream operations
	for _, downstream := range cfg.CascadesTo {
		if err := resetOpWithCascade(ctx, book, tocDocID, downstream); err != nil {
			return err
		}
	}

	return nil
}

// resetOp performs the full reset sequence for a single operation:
// 1. Reset in-memory operation state
// 2. Run memory cleanup hook
// 3. Clear agent states (memory + DB)
// 4. Persist standard + extra DB fields
// 5. Run operation-specific DB hook
func resetOp(ctx context.Context, book *BookState, tocDocID string, op OpType) error {
	cfg, ok := OpRegistry[op]
	if !ok {
		return fmt.Errorf("unknown operation: %s", op)
	}

	// 1. Reset operation state
	book.OpReset(op)

	// 2. Run memory cleanup hook
	if cfg.ResetMemoryHook != nil {
		book.mu.Lock()
		cfg.ResetMemoryHook(book)
		book.mu.Unlock()
	}

	// 3. Clear agent states (memory + DB)
	for _, agentType := range cfg.AgentTypes {
		book.ClearAgentStates(agentType)
		if book.Store != nil {
			// Use Store-based deletion: query then delete
			if err := deleteAgentStatesForTypeViaStore(ctx, book.Store, book.BookID, agentType); err != nil {
				return fmt.Errorf("failed to delete %s agent states: %w", agentType, err)
			}
		} else {
			if err := DeleteAgentStatesForType(ctx, book.BookID, agentType); err != nil {
				return fmt.Errorf("failed to delete %s agent states: %w", agentType, err)
			}
		}
	}

	// 4. Build and persist DB fields
	docID := cfg.DocIDSource(book)
	if docID == "" {
		return nil // No document yet (e.g., no ToC record)
	}

	// Merge standard op state fields + extra reset fields
	fields := map[string]any{
		cfg.FieldPrefix + "_started":  false,
		cfg.FieldPrefix + "_complete": false,
		cfg.FieldPrefix + "_failed":   false,
		cfg.FieldPrefix + "_retries":  0,
	}
	for k, v := range cfg.ResetDBFields {
		fields[k] = v
	}

	writeOp := defra.WriteOp{
		Collection: cfg.Collection,
		DocID:      docID,
		Document:   fields,
		Op:         defra.OpUpdate,
	}
	if book.Store != nil {
		if _, err := book.Store.SendSync(ctx, writeOp); err != nil {
			return fmt.Errorf("failed to persist %s reset: %w", op, err)
		}
	} else if err := SendToSinkSync(ctx, writeOp); err != nil {
		return fmt.Errorf("failed to persist %s reset: %w", op, err)
	}

	// 5. Run operation-specific DB hook
	if cfg.ResetHook != nil {
		if err := cfg.ResetHook(ctx, book, tocDocID); err != nil {
			return err
		}
	}

	return nil
}

// deleteAgentStatesForTypeViaStore deletes agent states using the StateStore interface.
// This enables reset operations to work without a DefraDB client in context.
func deleteAgentStatesForTypeViaStore(ctx context.Context, store StateStore, bookID, agentType string) error {
	query := fmt.Sprintf(`{
		AgentState(filter: {book_id: {_eq: "%s"}, agent_type: {_eq: "%s"}}) {
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

	for _, s := range states {
		state, ok := s.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := state["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		if _, err := store.SendSync(ctx, defra.WriteOp{
			Collection: "AgentState",
			DocID:      docID,
			Op:         defra.OpDelete,
		}); err != nil {
			return fmt.Errorf("failed to delete agent state %s: %w", docID, err)
		}
	}

	return nil
}

// resetAllOcr resets ocr_complete and ocr_markdown for all pages.
func resetAllOcr(ctx context.Context, book *BookState) error {
	logger := svcctx.LoggerFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Reset in-memory state
	book.ForEachPage(func(pageNum int, state *PageState) {
		state.SetOcrMarkdown("")
	})

	// Reset in DB - query all pages and update
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, ocr_complete: {_eq: true}}) {
			_docID
		}
	}`, book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query pages for OCR reset: %w", err)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return nil
	}

	// Collect all ops for batch processing
	var ops []defra.WriteOp
	var skipCount int
	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected page data type during OCR reset", "type", fmt.Sprintf("%T", p))
			}
			continue
		}
		docID, ok := page["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during OCR reset", "page_data", page)
			}
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "Page",
			DocID:      docID,
			Document: map[string]any{
				"ocr_complete": false,
				"ocr_markdown": nil,
				"headings":     nil,
			},
			Op: defra.OpUpdate,
		})
	}

	// Send all ops in batch
	var failCount int
	if len(ops) > 0 {
		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to batch reset OCR: %w", err)
		}
		for _, r := range results {
			if r.Err != nil {
				failCount++
				if logger != nil {
					logger.Error("failed to reset OCR for page", "doc_id", r.DocID, "error", r.Err)
				}
			}
		}
	}

	resetCount := len(ops) - failCount
	if logger != nil {
		logger.Debug("reset OCR completed", "reset_count", resetCount, "skipped", skipCount, "failed", failCount, "book_id", book.BookID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("OCR reset had issues: skipped=%d, failed=%d", skipCount, failCount)
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
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
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
		TocEntry(filter: {toc_id: {_eq: "%s"}}) {
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
		// Use sync write to ensure link clearing completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "TocEntry",
			DocID:      docID,
			Document: map[string]any{
				"actual_page_id": nil,
			},
			Op: defra.OpUpdate,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to clear ToC entry link", "doc_id", docID, "error", err)
			}
			continue
		}
		clearCount++
	}

	if logger != nil {
		logger.Debug("ToC entry links clearing completed", "clear_count", clearCount, "skipped", skipCount, "failed", failCount, "toc_id", tocDocID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("ToC entry link clearing had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}

// deleteChapters deletes all chapters for a book.
func deleteChapters(ctx context.Context, bookID string) error {
	logger := svcctx.LoggerFrom(ctx)
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}) {
			_docID
		}
	}`, bookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query chapters for deletion: %w", err)
	}

	chapters, ok := resp.Data["Chapter"].([]any)
	if !ok || len(chapters) == 0 {
		return nil
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	var deleteCount, skipCount, failCount int
	for _, c := range chapters {
		chapter, ok := c.(map[string]any)
		if !ok {
			skipCount++
			if logger != nil {
				logger.Warn("unexpected chapter data type during deletion", "type", fmt.Sprintf("%T", c))
			}
			continue
		}
		docID, ok := chapter["_docID"].(string)
		if !ok || docID == "" {
			skipCount++
			if logger != nil {
				logger.Warn("missing or invalid _docID during chapter deletion", "chapter_data", chapter)
			}
			continue
		}
		// Use sync write to ensure deletion completes
		_, err := sink.SendSync(ctx, defra.WriteOp{
			Collection: "Chapter",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
		if err != nil {
			failCount++
			if logger != nil {
				logger.Error("failed to delete chapter", "doc_id", docID, "error", err)
			}
			continue
		}
		deleteCount++
	}

	if logger != nil {
		logger.Debug("chapter deletion completed", "delete_count", deleteCount, "skipped", skipCount, "failed", failCount, "book_id", bookID)
	}

	if skipCount > 0 || failCount > 0 {
		return fmt.Errorf("chapter deletion had issues: skipped=%d, failed=%d", skipCount, failCount)
	}
	return nil
}
