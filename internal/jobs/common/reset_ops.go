package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

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

	// 1. Explicit operator repair resets both status and semantic retry budget.
	// OpReset intentionally preserves retries for crash reopen and rollback, so
	// using it here would let the next async Start write resurrect an exhausted
	// budget after this function persisted retries=0.
	book.SetOpState(op, false, false, false, 0)

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
		Page(filter: {_bookID: {_eq: "%s"}, ocr_complete: {_eq: true}}) {
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
