package common

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateMissingPages creates page records in DefraDB for any pages not yet in the BookState.
// Returns the number of pages created.
func CreateMissingPages(ctx context.Context, book *BookState) (int, error) {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return 0, fmt.Errorf("defra sink not in context")
	}

	// Identify pages that need creation
	var newPageNums []int
	for pageNum := 1; pageNum <= book.TotalPages; pageNum++ {
		if book.GetPage(pageNum) == nil {
			newPageNums = append(newPageNums, pageNum)
		}
	}

	if len(newPageNums) == 0 {
		return 0, nil
	}

	// Batch create new pages in DB
	ops := make([]defra.WriteOp, len(newPageNums))
	for i, pageNum := range newPageNums {
		ops[i] = defra.WriteOp{
			Collection: "Page",
			Document: map[string]any{
				"book_id":          book.BookID,
				"page_num":         pageNum,
				"extract_complete": false,
				"ocr_complete":     false,
				"blend_complete":   false,
				"label_complete":   false,
			},
			Op: defra.OpCreate,
		}
	}

	results, err := sink.SendManySync(ctx, ops)
	if err != nil {
		return 0, fmt.Errorf("failed to batch create page records: %w", err)
	}

	// Update BookState with new page states
	book.mu.Lock()
	defer book.mu.Unlock()
	for i, pageNum := range newPageNums {
		state := NewPageState()
		state.SetPageDocID(results[i].DocID)
		book.Pages[pageNum] = state
	}

	return len(newPageNums), nil
}
