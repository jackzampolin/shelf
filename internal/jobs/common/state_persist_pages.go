package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
)

// PersistOcrResult creates OcrResult record, updates page header/footer and ocr_complete.
// Updates PageState in memory only after all DB operations succeed.
// Returns (allProvidersDone, error).
func (b *BookState) PersistOcrResult(ctx context.Context, pageNum int, provider string, ocrText string, header, footer string) (bool, error) {
	store := b.getStore(ctx)
	if store == nil {
		return false, fmt.Errorf("no store available")
	}

	pageState := b.GetPage(pageNum)
	if pageState == nil {
		return false, fmt.Errorf("page %d not found in state", pageNum)
	}

	pageDocID := pageState.GetPageDocID()
	if pageDocID == "" {
		return false, fmt.Errorf("page %d has no doc ID", pageNum)
	}

	// Create OcrResult record
	ocrResultDoc := map[string]any{
		"page_id":  pageDocID,
		"provider": provider,
		"text":     ocrText,
		"book_id":  b.BookID,
	}

	ocrResult, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "OcrResult",
		Document:   ocrResultDoc,
		Op:         defra.OpCreate,
	})
	if err != nil {
		return false, fmt.Errorf("failed to create OcrResult: %w", err)
	}

	// Check if all providers would be done after this update (before mutating memory)
	// Count how many providers are currently complete
	currentCount := 0
	for _, p := range b.OcrProviders {
		if pageState.OcrComplete(p) {
			currentCount++
		}
	}
	// If this provider isn't already complete, we're adding one more
	alreadyComplete := pageState.OcrComplete(provider)
	newCount := currentCount
	if !alreadyComplete {
		newCount++
	}
	wouldBeDone := newCount >= len(b.OcrProviders)

	// Update Page record with header/footer and ocr_complete
	pageUpdate := map[string]any{
		"header":       header,
		"footer":       footer,
		"ocr_complete": wouldBeDone,
	}

	pageResult, err := store.UpdateWithVersion(ctx, "Page", pageDocID, pageUpdate)
	if err != nil {
		return false, fmt.Errorf("failed to update page: %w", err)
	}

	// All DB operations succeeded - now update memory atomically
	b.mu.Lock()
	pageState.MarkOcrComplete(provider, ocrText)
	pageState.SetHeader(header)
	pageState.SetFooter(footer)
	b.trackCIDLocked("OcrResult", ocrResult.DocID, ocrResult.CID)
	b.trackCIDLocked("Page", pageDocID, pageResult.CID)
	pageState.SetPageCID(pageResult.CID)
	b.mu.Unlock()

	// Return actual allDone status based on updated memory
	return pageState.AllOcrDone(b.OcrProviders), nil
}

// PersistOcrMarkdown persists ocr_markdown and headings for a page. Updates PageState.
// Only updates memory after DB operation succeeds to maintain consistency.
func (b *BookState) PersistOcrMarkdown(ctx context.Context, pageNum int, markdown string, headings map[string]any) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	pageState := b.GetPage(pageNum)
	if pageState == nil {
		return fmt.Errorf("page %d not found in state", pageNum)
	}

	pageDocID := pageState.GetPageDocID()
	if pageDocID == "" {
		return fmt.Errorf("page %d has no doc ID", pageNum)
	}

	// Build headings JSON if provided
	var headingsJSON string
	if headings != nil {
		if h, ok := headings["headings"].(string); ok {
			headingsJSON = h
		}
	}

	updateDoc := map[string]any{
		"ocr_markdown": markdown,
	}
	if headingsJSON != "" {
		updateDoc["headings"] = headingsJSON
	}

	result, err := store.UpdateWithVersion(ctx, "Page", pageDocID, updateDoc)
	if err != nil {
		return fmt.Errorf("failed to update page OCR markdown: %w", err)
	}

	// DB operation succeeded - update memory atomically
	b.mu.Lock()
	pageState.SetOcrMarkdown(markdown)
	b.trackCIDLocked("Page", pageDocID, result.CID)
	pageState.SetPageCID(result.CID)
	b.mu.Unlock()

	return nil
}

// ResetAllOcr resets OCR state for all pages (memory + DB). Clears ocrMarkdown, ocrResults, headings.
// Only updates memory after all DB operations succeed to maintain consistency.
func (b *BookState) ResetAllOcr(ctx context.Context) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Query all pages with ocr_complete=true
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, ocr_complete: {_eq: true}}) {
			_docID
		}
	}`, b.BookID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query pages for OCR reset: %w", err)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		// No pages to reset in DB, but still reset memory state
		b.ForEachPage(func(pageNum int, state *PageState) {
			state.SetOcrMarkdown("")
		})
		return nil
	}

	// Collect update ops
	var ops []defra.WriteOp
	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := page["_docID"].(string)
		if !ok || docID == "" {
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

	// Batch update DB first
	if len(ops) > 0 {
		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to reset OCR: %w", err)
		}

		// Check for individual errors
		for _, r := range results {
			if r.Err != nil {
				return fmt.Errorf("failed to reset OCR for page %s: %w", r.DocID, r.Err)
			}
		}
	}

	// All DB operations succeeded - now reset memory state
	b.ForEachPage(func(pageNum int, state *PageState) {
		state.SetOcrMarkdown("")
	})

	return nil
}
