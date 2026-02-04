package common

import (
	"context"
	"fmt"
	"strings"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
)

// maxConcurrentChapterWrites limits concurrent chapter DB writes.
const maxConcurrentChapterWrites = 5

// chapterResult holds the result of a chapter persist operation.
type chapterResult struct {
	entryID string
	docID   string
	cid     string
	err     error
}

// PersistChapterSkeleton upserts all chapters to DB, updates DocID/CID in BookState.
// Uses bounded concurrent goroutines for performance.
// Only updates memory state on full success to maintain consistency.
func (b *BookState) PersistChapterSkeleton(ctx context.Context, genUniqueKey func(*ChapterState) string) error {
	chapters := b.GetStructureChapters()
	if len(chapters) == 0 {
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Collect results via channel - don't mutate chapters in goroutines
	results := make(chan chapterResult, len(chapters))
	sem := make(chan struct{}, maxConcurrentChapterWrites)
	var wg sync.WaitGroup

	for i, ch := range chapters {
		wg.Add(1)
		go func(idx int, chapter *ChapterState) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results <- chapterResult{
						entryID: chapter.EntryID,
						err:     fmt.Errorf("panic in chapter %s: %v", chapter.EntryID, r),
					}
				}
			}()

			// Acquire semaphore
			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				results <- chapterResult{entryID: chapter.EntryID, err: ctx.Err()}
				return
			}

			uniqueKey := genUniqueKey(chapter)

			filter := map[string]any{"unique_key": uniqueKey}
			createInput := map[string]any{
				"unique_key":   uniqueKey,
				"book_id":      b.BookID,
				"entry_id":     chapter.EntryID,
				"title":        chapter.Title,
				"level":        chapter.Level,
				"level_name":   chapter.LevelName,
				"entry_number": chapter.EntryNumber,
				"sort_order":   chapter.SortOrder,
				"source":       chapter.Source,
				"toc_entry_id": chapter.TocEntryID,
				"start_page":   chapter.StartPage,
				"end_page":     chapter.EndPage,
				"parent_id":    chapter.ParentID,
			}
			updateInput := map[string]any{
				"title":        chapter.Title,
				"level":        chapter.Level,
				"level_name":   chapter.LevelName,
				"entry_number": chapter.EntryNumber,
				"sort_order":   chapter.SortOrder,
				"source":       chapter.Source,
				"start_page":   chapter.StartPage,
				"end_page":     chapter.EndPage,
				"parent_id":    chapter.ParentID,
			}

			result, err := store.UpsertWithVersion(ctx, "Chapter", filter, createInput, updateInput)
			if err != nil {
				results <- chapterResult{entryID: chapter.EntryID, err: fmt.Errorf("chapter %s: %w", chapter.EntryID, err)}
				return
			}

			results <- chapterResult{
				entryID: chapter.EntryID,
				docID:   result.DocID,
				cid:     result.CID,
			}
		}(i, ch)
	}

	// Wait for all goroutines and close channel
	go func() {
		wg.Wait()
		close(results)
	}()

	// Collect all results and errors
	resultMap := make(map[string]chapterResult)
	var errors []string
	for r := range results {
		if r.err != nil {
			errors = append(errors, r.err.Error())
		} else {
			resultMap[r.entryID] = r
		}
	}

	// If any errors, return aggregated error without updating memory
	if len(errors) > 0 {
		return fmt.Errorf("failed to persist %d chapters: %s", len(errors), strings.Join(errors, "; "))
	}

	// All succeeded - update chapters and memory atomically
	for _, ch := range chapters {
		if r, ok := resultMap[ch.EntryID]; ok {
			ch.UniqueKey = genUniqueKey(ch)
			ch.DocID = r.docID
			ch.CID = r.cid
		}
	}

	b.mu.Lock()
	b.structureChapters = chapters
	for _, ch := range chapters {
		b.trackCIDLocked("Chapter", ch.DocID, ch.CID)
	}
	b.mu.Unlock()

	return nil
}

// PersistChapterExtracts persists extract results (mechanical_text, word_count) for done chapters.
// Uses bounded concurrent goroutines for performance.
func (b *BookState) PersistChapterExtracts(ctx context.Context) error {
	chapters := b.GetStructureChapters()
	if len(chapters) == 0 {
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Filter to chapters that need persisting
	var toUpdate []*ChapterState
	for _, ch := range chapters {
		if ch.ExtractDone && ch.DocID != "" {
			toUpdate = append(toUpdate, ch)
		}
	}

	if len(toUpdate) == 0 {
		return nil
	}

	results := make(chan chapterResult, len(toUpdate))
	sem := make(chan struct{}, maxConcurrentChapterWrites)
	var wg sync.WaitGroup

	for _, ch := range toUpdate {
		wg.Add(1)
		go func(chapter *ChapterState) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results <- chapterResult{
						entryID: chapter.EntryID,
						err:     fmt.Errorf("panic in chapter %s: %v", chapter.EntryID, r),
					}
				}
			}()

			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				results <- chapterResult{entryID: chapter.EntryID, err: ctx.Err()}
				return
			}

			result, err := store.UpdateWithVersion(ctx, "Chapter", chapter.DocID, map[string]any{
				"mechanical_text": chapter.MechanicalText,
				"extract_done":    chapter.ExtractDone,
			})
			if err != nil {
				results <- chapterResult{entryID: chapter.EntryID, err: fmt.Errorf("chapter %s: %w", chapter.EntryID, err)}
				return
			}

			results <- chapterResult{
				entryID: chapter.EntryID,
				docID:   chapter.DocID,
				cid:     result.CID,
			}
		}(ch)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	// Collect results
	resultMap := make(map[string]chapterResult)
	var errors []string
	for r := range results {
		if r.err != nil {
			errors = append(errors, r.err.Error())
		} else {
			resultMap[r.entryID] = r
		}
	}

	if len(errors) > 0 {
		return fmt.Errorf("failed to persist extracts for %d chapters: %s", len(errors), strings.Join(errors, "; "))
	}

	// Update memory only on full success
	b.mu.Lock()
	for _, ch := range toUpdate {
		if r, ok := resultMap[ch.EntryID]; ok {
			ch.CID = r.cid
			b.trackCIDLocked("Chapter", ch.DocID, ch.CID)
		}
	}
	b.structureChapters = chapters // Replace with updated copies
	b.mu.Unlock()

	return nil
}

// PersistChapterClassifications persists classify results for all chapters.
// Uses bounded concurrent goroutines for performance.
func (b *BookState) PersistChapterClassifications(ctx context.Context) error {
	chapters := b.GetStructureChapters()
	if len(chapters) == 0 {
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Filter to chapters with classifications
	var toUpdate []*ChapterState
	for _, ch := range chapters {
		if ch.DocID != "" && ch.MatterType != "" {
			toUpdate = append(toUpdate, ch)
		}
	}

	if len(toUpdate) == 0 {
		return nil
	}

	results := make(chan chapterResult, len(toUpdate))
	sem := make(chan struct{}, maxConcurrentChapterWrites)
	var wg sync.WaitGroup

	for _, ch := range toUpdate {
		wg.Add(1)
		go func(chapter *ChapterState) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results <- chapterResult{
						entryID: chapter.EntryID,
						err:     fmt.Errorf("panic in chapter %s: %v", chapter.EntryID, r),
					}
				}
			}()

			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				results <- chapterResult{entryID: chapter.EntryID, err: ctx.Err()}
				return
			}

			result, err := store.UpdateWithVersion(ctx, "Chapter", chapter.DocID, map[string]any{
				"matter_type":             chapter.MatterType,
				"classify_reasoning":      chapter.ClassifyReasoning,
				"content_type":            chapter.ContentType,
				"audio_include":           chapter.AudioInclude,
				"audio_include_reasoning": chapter.AudioIncludeReasoning,
			})
			if err != nil {
				results <- chapterResult{entryID: chapter.EntryID, err: fmt.Errorf("chapter %s: %w", chapter.EntryID, err)}
				return
			}

			results <- chapterResult{
				entryID: chapter.EntryID,
				docID:   chapter.DocID,
				cid:     result.CID,
			}
		}(ch)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	// Collect results
	resultMap := make(map[string]chapterResult)
	var errors []string
	for r := range results {
		if r.err != nil {
			errors = append(errors, r.err.Error())
		} else {
			resultMap[r.entryID] = r
		}
	}

	if len(errors) > 0 {
		return fmt.Errorf("failed to persist classifications for %d chapters: %s", len(errors), strings.Join(errors, "; "))
	}

	// Update memory only on full success
	b.mu.Lock()
	for _, ch := range toUpdate {
		if r, ok := resultMap[ch.EntryID]; ok {
			ch.CID = r.cid
			b.trackCIDLocked("Chapter", ch.DocID, ch.CID)
		}
	}
	b.structureChapters = chapters // Replace with updated copies
	b.mu.Unlock()

	return nil
}

// PersistChapterPolish persists polish results (polished_text, word_count, etc.) for done chapters.
// Uses bounded concurrent goroutines for performance.
func (b *BookState) PersistChapterPolish(ctx context.Context) error {
	chapters := b.GetStructureChapters()
	if len(chapters) == 0 {
		return nil
	}

	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Filter to chapters that need persisting
	var toUpdate []*ChapterState
	for _, ch := range chapters {
		if ch.DocID != "" && ch.PolishDone {
			toUpdate = append(toUpdate, ch)
		}
	}

	if len(toUpdate) == 0 {
		return nil
	}

	results := make(chan chapterResult, len(toUpdate))
	sem := make(chan struct{}, maxConcurrentChapterWrites)
	var wg sync.WaitGroup

	for _, ch := range toUpdate {
		wg.Add(1)
		go func(chapter *ChapterState) {
			defer wg.Done()
			defer func() {
				if r := recover(); r != nil {
					results <- chapterResult{
						entryID: chapter.EntryID,
						err:     fmt.Errorf("panic in chapter %s: %v", chapter.EntryID, r),
					}
				}
			}()

			select {
			case sem <- struct{}{}:
				defer func() { <-sem }()
			case <-ctx.Done():
				results <- chapterResult{entryID: chapter.EntryID, err: ctx.Err()}
				return
			}

			result, err := store.UpdateWithVersion(ctx, "Chapter", chapter.DocID, map[string]any{
				"polished_text": chapter.PolishedText,
				"word_count":    chapter.WordCount,
				"polish_done":   chapter.PolishDone,
				"polish_failed": chapter.PolishFailed,
			})
			if err != nil {
				results <- chapterResult{entryID: chapter.EntryID, err: fmt.Errorf("chapter %s: %w", chapter.EntryID, err)}
				return
			}

			results <- chapterResult{
				entryID: chapter.EntryID,
				docID:   chapter.DocID,
				cid:     result.CID,
			}
		}(ch)
	}

	go func() {
		wg.Wait()
		close(results)
	}()

	// Collect results
	resultMap := make(map[string]chapterResult)
	var errors []string
	for r := range results {
		if r.err != nil {
			errors = append(errors, r.err.Error())
		} else {
			resultMap[r.entryID] = r
		}
	}

	if len(errors) > 0 {
		return fmt.Errorf("failed to persist polish for %d chapters: %s", len(errors), strings.Join(errors, "; "))
	}

	// Update memory only on full success
	b.mu.Lock()
	for _, ch := range toUpdate {
		if r, ok := resultMap[ch.EntryID]; ok {
			ch.CID = r.cid
			b.trackCIDLocked("Chapter", ch.DocID, ch.CID)
		}
	}
	b.structureChapters = chapters // Replace with updated copies
	b.mu.Unlock()

	return nil
}

// DeleteAllChapters deletes all Chapter records for this book and clears b.structureChapters.
func (b *BookState) DeleteAllChapters(ctx context.Context) error {
	store := b.getStore(ctx)
	if store == nil {
		return fmt.Errorf("no store available")
	}

	// Query for all chapters
	query := fmt.Sprintf(`{
		Chapter(filter: {book_id: {_eq: "%s"}}) {
			_docID
		}
	}`, b.BookID)

	resp, err := store.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query chapters for deletion: %w", err)
	}

	chapters, ok := resp.Data["Chapter"].([]any)
	if !ok || len(chapters) == 0 {
		// No chapters to delete, just clear memory
		b.mu.Lock()
		b.structureChapters = nil
		b.mu.Unlock()
		return nil
	}

	// Collect delete ops
	var ops []defra.WriteOp
	for _, c := range chapters {
		chapter, ok := c.(map[string]any)
		if !ok {
			continue
		}
		docID, ok := chapter["_docID"].(string)
		if !ok || docID == "" {
			continue
		}
		ops = append(ops, defra.WriteOp{
			Collection: "Chapter",
			DocID:      docID,
			Op:         defra.OpDelete,
		})
	}

	// Batch delete and check individual results
	if len(ops) > 0 {
		results, err := store.SendManySync(ctx, ops)
		if err != nil {
			return fmt.Errorf("failed to delete chapters: %w", err)
		}

		// Check individual results for errors
		var errors []string
		for i, r := range results {
			if r.Err != nil {
				errors = append(errors, fmt.Sprintf("chapter %s: %v", ops[i].DocID, r.Err))
			}
		}
		if len(errors) > 0 {
			return fmt.Errorf("failed to delete %d chapters: %s", len(errors), strings.Join(errors, "; "))
		}
	}

	// Clear memory only after all deletes succeed
	b.mu.Lock()
	b.structureChapters = nil
	b.mu.Unlock()

	return nil
}
