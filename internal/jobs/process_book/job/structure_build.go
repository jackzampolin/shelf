package job

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

type chapterDocIdentity struct {
	DocID     string
	UniqueKey string
}

// buildChapterSkeleton builds the chapter skeleton from linked ToC entries.
func (j *Job) buildChapterSkeleton(ctx context.Context, entries []*common.LinkedTocEntry) error {
	logger := svcctx.LoggerFrom(ctx)

	// Filter to entries with actual pages
	var linkedEntries []*common.LinkedTocEntry
	for _, entry := range entries {
		if entry.ActualPage != nil {
			linkedEntries = append(linkedEntries, entry)
		}
	}

	if len(linkedEntries) == 0 {
		return fmt.Errorf("no linked ToC entries found")
	}

	// Sort by sort_order
	sort.Slice(linkedEntries, func(i, k int) bool {
		return linkedEntries[i].SortOrder < linkedEntries[k].SortOrder
	})

	// Create chapters with boundaries
	chapters := make([]*common.ChapterState, 0, len(linkedEntries))
	for i, entry := range linkedEntries {
		chapter := &common.ChapterState{
			EntryID:     fmt.Sprintf("ch_%03d", i+1),
			Title:       entry.Title,
			Level:       entry.Level,
			LevelName:   entry.LevelName,
			EntryNumber: entry.EntryNumber,
			SortOrder:   entry.SortOrder,
			Source:      "toc",
			TocEntryID:  entry.DocID,
			StartPage:   *entry.ActualPage,
			MatterType:  "body", // Default, updated in classify phase
		}

		// Calculate end page
		if i < len(linkedEntries)-1 {
			nextEntry := linkedEntries[i+1]
			if nextEntry.ActualPage != nil {
				chapter.EndPage = *nextEntry.ActualPage - 1
			}
		} else {
			chapter.EndPage = j.Book.TotalPages
		}

		// Ensure end_page >= start_page
		if chapter.EndPage < chapter.StartPage {
			chapter.EndPage = chapter.StartPage
		}

		chapters = append(chapters, chapter)
	}

	// Store chapters on BookState
	j.Book.SetStructureChapters(chapters)

	// Build hierarchy (set parent_id based on levels)
	j.buildChapterHierarchy()

	if logger != nil {
		logger.Debug("built chapter skeleton",
			"book_id", j.Book.BookID,
			"chapters", len(chapters))
	}

	// Persist skeleton to DefraDB
	return j.persistChapterSkeleton(ctx)
}

// buildChapterHierarchy sets parent_id values based on chapter levels.
func (j *Job) buildChapterHierarchy() {
	recentByLevel := make(map[int]*common.ChapterState)
	chapters := j.Book.GetStructureChapters()

	for _, chapter := range chapters {
		if chapter.Level > 1 {
			if parent, ok := recentByLevel[chapter.Level-1]; ok {
				chapter.ParentID = parent.EntryID
				j.Book.UpdateChapter(chapter) // Save changes back
			}
		}
		recentByLevel[chapter.Level] = chapter
		for lvl := chapter.Level + 1; lvl <= 5; lvl++ {
			delete(recentByLevel, lvl)
		}
	}
}

// persistChapterSkeleton saves the chapter skeleton to DefraDB using upsert.
// This preserves DocIDs/CIDs across re-runs, enabling change history tracking.
func (j *Job) persistChapterSkeleton(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	logger := svcctx.LoggerFrom(ctx)

	// Mark structure as started on Book
	if _, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"structure_started": true,
		},
		Op: defra.OpUpdate,
	}); err != nil && logger != nil {
		logger.Warn("failed to persist structure start", "book_id", j.Book.BookID, "error", err)
	}

	chapters := j.Book.GetStructureChapters()

	// Pre-compute unique keys (must happen before concurrent access)
	for _, chapter := range chapters {
		chapter.UniqueKey = j.generateChapterUniqueKey(chapter)
	}

	// Upsert chapters concurrently with bounded parallelism
	var wg sync.WaitGroup
	sem := make(chan struct{}, maxPersistConcurrency)
	var mu sync.Mutex
	var firstErr error

	for _, chapter := range chapters {
		wg.Add(1)
		go func(ch *common.ChapterState) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			doc := map[string]any{
				"_bookID":      j.Book.BookID,
				"unique_key":   ch.UniqueKey,
				"entry_id":     ch.EntryID,
				"title":        ch.Title,
				"level":        ch.Level,
				"level_name":   ch.LevelName,
				"entry_number": ch.EntryNumber,
				"sort_order":   ch.SortOrder,
				"start_page":   ch.StartPage,
				"end_page":     ch.EndPage,
				"matter_type":  ch.MatterType,
				"parent_id":    ch.ParentID,
				"source":       ch.Source,
			}

			if ch.TocEntryID != "" {
				doc["_toc_entryID"] = ch.TocEntryID
			}

			result, err := j.persistChapterSkeletonDoc(ctx, defraClient, ch, doc)
			if err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = fmt.Errorf("failed to upsert chapter %s: %w", ch.EntryID, err)
				}
				mu.Unlock()
				return
			}
			docID := result.DocID
			if docID == "" {
				docID = ch.DocID
			}
			ch.DocID = docID
			ch.CID = result.CID
			j.Book.UpdateChapter(ch)
			j.Book.TrackWrite("Chapter", docID, result.CID)

			if logger != nil {
				logger.Debug("upserted chapter", "entry_id", ch.EntryID, "unique_key", ch.UniqueKey, "doc_id", docID)
			}
		}(chapter)
	}
	wg.Wait()

	if firstErr != nil {
		return firstErr
	}
	return j.deleteStaleStructureChapters(ctx, defraClient, chapters)
}

func (j *Job) persistChapterSkeletonDoc(ctx context.Context, defraClient *defra.Client, ch *common.ChapterState, doc map[string]any) (defra.WriteResult, error) {
	filter := map[string]any{
		"unique_key": map[string]any{"_eq": ch.UniqueKey},
	}

	result, err := defraStructureWriteWithRetry(ctx, func() (defra.WriteResult, error) {
		return defraClient.UpsertWithVersion(ctx, "Chapter", filter, doc, doc)
	})
	if err == nil || !isDefraDocIDExistsError(err) {
		return result, err
	}

	existing, findErr := j.findExistingChapterByIdentity(ctx, defraClient, ch)
	if findErr != nil {
		return defra.WriteResult{}, findErr
	}
	if existing == nil {
		return defra.WriteResult{}, fmt.Errorf("chapter stable-key upsert collided for %s (%s), but no existing Chapter matched book/ToC identity: %w", ch.EntryID, ch.UniqueKey, err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Warn("chapter upsert collided with existing DocID; updating existing chapter by identity",
			"entry_id", ch.EntryID,
			"unique_key", ch.UniqueKey,
			"existing_doc_id", existing.DocID,
			"existing_unique_key", existing.UniqueKey,
			"error", err)
	}

	return defraStructureWriteWithRetry(ctx, func() (defra.WriteResult, error) {
		return defraClient.UpdateWithVersion(ctx, "Chapter", existing.DocID, doc)
	})
}

func (j *Job) findExistingChapterByIdentity(ctx context.Context, defraClient *defra.Client, ch *common.ChapterState) (*chapterDocIdentity, error) {
	query := fmt.Sprintf(`{
		Chapter(filter: {_bookID: {_eq: %s}}, order: {sort_order: ASC}, limit: 5000) {
			_docID
			unique_key
			entry_id
			sort_order
			_toc_entryID
		}
	}`, gqlString(j.Book.BookID))

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query existing chapters for identity match: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("failed to query existing chapters for identity match: %s", errMsg)
	}

	raw, ok := resp.Data["Chapter"].([]any)
	if !ok {
		return nil, fmt.Errorf("unexpected Chapter identity query response: %+v", resp.Data)
	}

	var matches []chapterDocIdentity
	for _, item := range raw {
		data, ok := item.(map[string]any)
		if !ok || !chapterIdentityMatches(data, ch) {
			continue
		}
		docID, _ := data["_docID"].(string)
		if docID == "" {
			continue
		}
		uniqueKey, _ := data["unique_key"].(string)
		matches = append(matches, chapterDocIdentity{
			DocID:     docID,
			UniqueKey: uniqueKey,
		})
	}

	if len(matches) == 0 {
		return nil, nil
	}
	if len(matches) > 1 {
		return nil, fmt.Errorf("multiple existing Chapter records matched identity for %s (%s)", ch.EntryID, ch.UniqueKey)
	}
	return &matches[0], nil
}

func (j *Job) deleteStaleStructureChapters(ctx context.Context, defraClient *defra.Client, current []*common.ChapterState) error {
	currentDocIDs := make(map[string]bool, len(current))
	for _, chapter := range current {
		if chapter != nil && chapter.DocID != "" {
			currentDocIDs[chapter.DocID] = true
		}
	}

	query := fmt.Sprintf(`{
		Chapter(filter: {_bookID: {_eq: %s}}, order: {sort_order: ASC}, limit: 5000) {
			_docID
			entry_id
			sort_order
			_toc_entryID
		}
	}`, gqlString(j.Book.BookID))

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query stale chapters: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("failed to query stale chapters: %s", errMsg)
	}

	raw, ok := resp.Data["Chapter"].([]any)
	if !ok {
		return fmt.Errorf("unexpected stale Chapter query response: %+v", resp.Data)
	}

	logger := svcctx.LoggerFrom(ctx)
	deleted := 0
	for _, item := range raw {
		data, ok := item.(map[string]any)
		if !ok {
			continue
		}
		docID, _ := data["_docID"].(string)
		if docID == "" || currentDocIDs[docID] {
			continue
		}
		_, err := defraStructureWriteWithRetry(ctx, func() (defra.WriteResult, error) {
			return defra.WriteResult{}, defraClient.Delete(ctx, "Chapter", docID)
		})
		if err != nil {
			return fmt.Errorf("failed to delete stale chapter %s: %w", docID, err)
		}
		deleted++
	}
	if deleted > 0 && logger != nil {
		logger.Debug("deleted stale structure chapters", "book_id", j.Book.BookID, "count", deleted)
	}
	return nil
}

func chapterIdentityMatches(data map[string]any, ch *common.ChapterState) bool {
	if ch.TocEntryID != "" {
		tocEntryID, _ := data["_toc_entryID"].(string)
		return tocEntryID == ch.TocEntryID
	}

	entryID, _ := data["entry_id"].(string)
	sortOrder, ok := graphQLInt(data["sort_order"])
	return entryID == ch.EntryID && ok && sortOrder == ch.SortOrder
}

func graphQLInt(v any) (int, bool) {
	switch n := v.(type) {
	case int:
		return n, true
	case int64:
		return int(n), true
	case float64:
		return int(n), true
	case json.Number:
		i, err := n.Int64()
		if err != nil {
			return 0, false
		}
		return int(i), true
	default:
		return 0, false
	}
}

// generateChapterUniqueKey creates a stable unique_key for upsert.
// Format: "{book_id}:{toc_entry_id}" for ToC-linked chapters,
// or "{book_id}:orphan:{sort_order}" for chapters without ToC entries.
func (j *Job) generateChapterUniqueKey(chapter *common.ChapterState) string {
	if chapter.TocEntryID != "" {
		return fmt.Sprintf("%s:%s", j.Book.BookID, chapter.TocEntryID)
	}
	// Orphan chapters (not from ToC) use sort_order for stability
	return fmt.Sprintf("%s:orphan:%d", j.Book.BookID, chapter.SortOrder)
}
