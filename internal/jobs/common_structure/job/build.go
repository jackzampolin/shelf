package job

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// BuildSkeleton builds the chapter skeleton from linked ToC entries.
// This is Phase 1 of the common-structure job.
func (j *Job) BuildSkeleton(ctx context.Context) error {
	logger := svcctx.LoggerFrom(ctx)

	// Filter to only entries with actual pages
	var linkedEntries []*LinkedTocEntry
	for _, entry := range j.LinkedEntries {
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
	for i, entry := range linkedEntries {
		chapter := &ChapterState{
			EntryID:     fmt.Sprintf("ch_%03d", i+1),
			Title:       entry.Title,
			Level:       entry.Level,
			LevelName:   entry.LevelName,
			EntryNumber: entry.EntryNumber,
			SortOrder:   entry.SortOrder,
			Source:      "toc",
			TocEntryID:  entry.DocID,
			StartPage:   *entry.ActualPage,
			MatterType:  "body", // Default, will be updated in classify phase
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

		j.Chapters = append(j.Chapters, chapter)
	}

	// Build hierarchy (set parent_id based on levels)
	j.buildHierarchy()

	if logger != nil {
		logger.Info("built chapter skeleton",
			"book_id", j.Book.BookID,
			"chapters", len(j.Chapters))
	}

	// Persist skeleton to DefraDB
	return j.persistSkeleton(ctx)
}

// buildHierarchy sets parent_id values based on chapter levels.
func (j *Job) buildHierarchy() {
	recentByLevel := make(map[int]*ChapterState)

	for _, chapter := range j.Chapters {
		if chapter.Level > 1 {
			// Look for parent at level-1
			if parent, ok := recentByLevel[chapter.Level-1]; ok {
				chapter.ParentID = parent.EntryID
			}
		}

		// Update recent entry for this level
		recentByLevel[chapter.Level] = chapter

		// Clear deeper levels
		for lvl := chapter.Level + 1; lvl <= 5; lvl++ {
			delete(recentByLevel, lvl)
		}
	}
}

// persistSkeleton saves the chapter skeleton to DefraDB.
func (j *Job) persistSkeleton(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Mark structure as started on Book
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"structure_started": true,
		},
		Op: defra.OpUpdate,
	})

	// Create Chapter records
	var chapterOps []defra.WriteOp
	for _, chapter := range j.Chapters {
		doc := map[string]any{
			"book_id":      j.Book.BookID,
			"entry_id":     chapter.EntryID,
			"title":        chapter.Title,
			"level":        chapter.Level,
			"level_name":   chapter.LevelName,
			"entry_number": chapter.EntryNumber,
			"sort_order":   chapter.SortOrder,
			"start_page":   chapter.StartPage,
			"end_page":     chapter.EndPage,
			"matter_type":  chapter.MatterType,
			"parent_id":    chapter.ParentID,
			"source":       chapter.Source,
		}

		// Add toc_entry relationship if we have the DocID
		if chapter.TocEntryID != "" {
			doc["toc_entry_id"] = chapter.TocEntryID
		}

		chapterOps = append(chapterOps, defra.WriteOp{
			Collection: "Chapter",
			Document:   doc,
			Op:         defra.OpCreate,
		})
	}

	// Batch create chapters
	results, err := sink.SendManySync(ctx, chapterOps)
	if err != nil {
		return fmt.Errorf("failed to create chapters: %w", err)
	}

	// Store DocIDs on chapter state
	for i, result := range results {
		if i < len(j.Chapters) {
			j.Chapters[i].DocID = result.DocID
		}
	}

	return nil
}

// GetChapterByEntryID returns a chapter by its entry_id.
func (j *Job) GetChapterByEntryID(entryID string) *ChapterState {
	for _, ch := range j.Chapters {
		if ch.EntryID == entryID {
			return ch
		}
	}
	return nil
}

// loadExistingChapters loads chapters from DB for recovery scenarios.
func (j *Job) loadExistingChapters(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Chapter(filter: {book: {_docID: {_eq: %q}}}, order: {sort_order: ASC}) {
			_docID
			entry_id
			title
			level
			level_name
			entry_number
			sort_order
			start_page
			end_page
			matter_type
			classification_reasoning
			parent_id
			source
			mechanical_text
			polished_text
			word_count
			polish_complete
		}
	}`, j.Book.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	chapters, ok := resp.Data["Chapter"].([]any)
	if !ok {
		return nil // No chapters yet
	}

	j.Chapters = make([]*ChapterState, 0, len(chapters))
	for _, c := range chapters {
		cm, ok := c.(map[string]any)
		if !ok {
			continue
		}

		chapter := &ChapterState{
			DocID:             getString(cm, "_docID"),
			EntryID:           getString(cm, "entry_id"),
			Title:             getString(cm, "title"),
			Level:             getInt(cm, "level"),
			LevelName:         getString(cm, "level_name"),
			EntryNumber:       getString(cm, "entry_number"),
			SortOrder:         getInt(cm, "sort_order"),
			StartPage:         getInt(cm, "start_page"),
			EndPage:           getInt(cm, "end_page"),
			MatterType:        getString(cm, "matter_type"),
			ClassifyReasoning: getString(cm, "classification_reasoning"),
			ParentID:          getString(cm, "parent_id"),
			Source:            getString(cm, "source"),
			MechanicalText:    getString(cm, "mechanical_text"),
			PolishedText:      getString(cm, "polished_text"),
			WordCount:         getInt(cm, "word_count"),
			PolishDone:        getBool(cm, "polish_complete"),
			ExtractDone:       getString(cm, "mechanical_text") != "",
		}

		j.Chapters = append(j.Chapters, chapter)
	}

	// Update progress counters
	j.ChaptersExtracted = 0
	j.ChaptersPolished = 0
	for _, ch := range j.Chapters {
		if ch.ExtractDone {
			j.ChaptersExtracted++
		}
		if ch.PolishDone {
			j.ChaptersPolished++
		}
	}

	return nil
}

// Helper functions for type conversion
func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

func getInt(m map[string]any, key string) int {
	if v, ok := m[key].(float64); ok {
		return int(v)
	}
	return 0
}

func getBool(m map[string]any, key string) bool {
	if v, ok := m[key].(bool); ok {
		return v
	}
	return false
}
