package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// completeStructurePhase finalizes the structure job.
func (j *Job) completeStructurePhase(ctx context.Context) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)
	_, _, _, polishFailed := j.Book.GetStructureProgress()
	if polishFailed > 0 {
		return nil, fmt.Errorf(
			"structure polish failed for %d chapter(s); mechanical fallback is not certifiable",
			polishFailed,
		)
	}

	if err := j.validatePersistedStructureChapters(ctx); err != nil {
		if logger != nil {
			logger.Error("persisted structure chapter validation failed", "error", err)
		}
		return nil, err
	}

	j.Book.SetStructurePhase(StructPhaseFinalize)
	// Persist phase (async - memory is authoritative, continue even if persist fails)
	common.PersistStructurePhaseAsync(ctx, j.Book)

	// Finalize - create paragraphs, update book status
	if err := j.finalizeStructure(ctx); err != nil {
		if logger != nil {
			logger.Error("failed to finalize structure", "error", err)
		}
		return nil, fmt.Errorf("finalization failed: %w", err)
	}

	// For critical completion operations: sync write BEFORE updating memory.
	// This ensures memory and DB stay consistent - if write fails, memory is unchanged.
	if _, err := common.PersistOpComplete(ctx, j.Book, common.OpStructure); err != nil {
		if logger != nil {
			logger.Error("failed to persist structure completion", "error", err)
		}
		// Memory wasn't marked complete yet, so no rollback needed
		return nil, fmt.Errorf("structure completed but failed to persist: %w", err)
	}

	// NOW mark complete in memory after successful DB write
	j.Book.StructureComplete()

	chapters := j.Book.GetStructureChapters()
	_, _, polished, failed := j.Book.GetStructureProgress()
	if logger != nil {
		logger.Info("structure phase complete",
			"book_id", j.Book.BookID,
			"chapters", len(chapters),
			"polished", polished,
			"failed", failed)
	}

	return nil, nil
}

func (j *Job) validatePersistedStructureChapters(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	chapters := j.Book.GetStructureChapters()
	if len(chapters) == 0 {
		return fmt.Errorf("no structure chapters to validate")
	}

	query := fmt.Sprintf(`{
		Chapter(filter: {_bookID: {_eq: %s}}, order: {sort_order: ASC}, limit: 5000) {
			_docID
			entry_id
			sort_order
			_toc_entryID
			extract_complete
			polish_complete
			matter_type
			content_type
			audio_include
		}
	}`, gqlString(j.Book.BookID))

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return fmt.Errorf("failed to query persisted structure chapters: %w", err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("failed to query persisted structure chapters: %s", errMsg)
	}

	raw, ok := resp.Data["Chapter"].([]any)
	if !ok {
		return fmt.Errorf("unexpected Chapter validation response: %+v", resp.Data)
	}

	byDocID := make(map[string]map[string]any, len(raw))
	var rows []map[string]any
	for _, item := range raw {
		data, ok := item.(map[string]any)
		if !ok {
			continue
		}
		rows = append(rows, data)
		if docID, _ := data["_docID"].(string); docID != "" {
			byDocID[docID] = data
		}
	}

	var problems []string
	for _, chapter := range chapters {
		data := byDocID[chapter.DocID]
		if data == nil {
			for _, row := range rows {
				if chapterIdentityMatches(row, chapter) {
					data = row
					break
				}
			}
		}
		if data == nil {
			problems = append(problems, fmt.Sprintf("%s missing persisted Chapter row", chapter.EntryID))
			continue
		}

		if extractComplete, _ := data["extract_complete"].(bool); !extractComplete {
			problems = append(problems, fmt.Sprintf("%s missing extract_complete", chapter.EntryID))
		}
		if chapter.PolishDone {
			if polishComplete, _ := data["polish_complete"].(bool); !polishComplete {
				problems = append(problems, fmt.Sprintf("%s missing polish_complete", chapter.EntryID))
			}
		}
		if matterType, _ := data["matter_type"].(string); strings.TrimSpace(matterType) == "" {
			problems = append(problems, fmt.Sprintf("%s missing matter_type", chapter.EntryID))
		}
		if contentType, _ := data["content_type"].(string); strings.TrimSpace(contentType) == "" {
			problems = append(problems, fmt.Sprintf("%s missing content_type", chapter.EntryID))
		}
		if _, ok := data["audio_include"].(bool); !ok {
			problems = append(problems, fmt.Sprintf("%s missing audio_include", chapter.EntryID))
		}
	}

	if len(problems) > 0 {
		return fmt.Errorf("persisted structure chapters incomplete: %s", strings.Join(problems, "; "))
	}
	return nil
}

// finalizeStructure marks structure as complete.
// Polish results were already persisted via sync writes in persistPolishResults.
// The sync write here ensures completion is durable before returning.
func (j *Job) finalizeStructure(ctx context.Context) error {
	totalChapters, totalWords := computeStructureStats(j.Book.GetStructureChapters())

	// Mark book structure as complete using sync write.
	// This ensures completion is durable before returning.
	_, err := common.SendTracked(ctx, j.Book, defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"structure_complete": true,
			"total_chapters":     totalChapters,
			"total_words":        totalWords,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return fmt.Errorf("failed to mark structure complete: %w", err)
	}

	return nil
}

func computeStructureStats(chapters []*common.ChapterState) (totalChapters, totalWords int) {
	for _, ch := range chapters {
		if ch == nil {
			continue
		}
		totalChapters++
		if ch.WordCount > 0 {
			totalWords += ch.WordCount
			continue
		}
		text := ch.PolishedText
		if text == "" {
			text = ch.MechanicalText
		}
		totalWords += common.CountWords(text)
	}
	return totalChapters, totalWords
}
