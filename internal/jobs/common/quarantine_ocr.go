package common

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

// QuarantineOCRPages marks known pathological pages as explicit terminal
// exceptions. It never fabricates OCR text or marks OCR successful. Callers
// should first use RepairOCRPages to remove any stale provider results.
func QuarantineOCRPages(ctx context.Context, book *BookState, pageNums []int, reason string) ([]int, error) {
	if book == nil {
		return nil, fmt.Errorf("book is required")
	}
	if book.Store == nil {
		return nil, fmt.Errorf("book state store is required")
	}
	reason = strings.TrimSpace(reason)
	if reason == "" {
		return nil, fmt.Errorf("quarantine reason is required")
	}
	pages, err := normalizeRepairPages(pageNums, book.TotalPages)
	if err != nil {
		return nil, err
	}

	type targetPage struct {
		state *PageState
		docID string
	}
	targets := make([]targetPage, 0, len(pages))
	ops := make([]defra.WriteOp, 0, len(pages))
	for _, pageNum := range pages {
		state := book.GetPage(pageNum)
		if state == nil {
			return nil, fmt.Errorf("page %d is not present in durable book state", pageNum)
		}
		docID := state.GetPageDocID()
		if docID == "" {
			return nil, fmt.Errorf("page %d has no durable document ID", pageNum)
		}
		targets = append(targets, targetPage{state: state, docID: docID})
		ops = append(ops, defra.WriteOp{
			Collection: "Page",
			DocID:      docID,
			Document: map[string]any{
				"ocr_complete":          false,
				"ocr_markdown":          nil,
				"headings":              nil,
				"header":                nil,
				"footer":                nil,
				"ocr_quarantined":       true,
				"ocr_quarantine_reason": reason,
			},
			Op:     defra.OpUpdate,
			Source: "QuarantineOCRPages",
		})
	}

	results, err := book.Store.SendManySync(ctx, ops)
	if err != nil {
		return nil, fmt.Errorf("persist OCR quarantine: %w", err)
	}
	for i, result := range results {
		if result.Err != nil {
			return nil, fmt.Errorf("persist OCR quarantine operation %d for %s: %w", i, result.DocID, result.Err)
		}
	}
	for _, target := range targets {
		target.state.QuarantineOCR(reason)
	}
	return pages, nil
}
