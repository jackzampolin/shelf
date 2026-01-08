package job

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// FinalizeStructure completes the structure processing by persisting
// all data and updating the Book record with totals.
func (j *Job) FinalizeStructure(ctx context.Context) error {
	logger := svcctx.LoggerFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Calculate totals
	totalChapters := len(j.Chapters)
	totalParagraphs := 0
	totalWords := 0

	for _, chapter := range j.Chapters {
		totalParagraphs += len(chapter.Paragraphs)
		totalWords += chapter.WordCount
	}

	// Create Paragraph records
	if err := j.createParagraphRecords(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to create paragraph records", "error", err)
		}
		// Continue anyway - chapters are still valid
	}

	// Update Book with totals and mark complete
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      j.Book.BookID,
		Document: map[string]any{
			"total_chapters":     totalChapters,
			"total_paragraphs":   totalParagraphs,
			"total_words":        totalWords,
			"structure_complete": true,
		},
		Op: defra.OpUpdate,
	})

	if logger != nil {
		logger.Info("finalized book structure",
			"book_id", j.Book.BookID,
			"chapters", totalChapters,
			"paragraphs", totalParagraphs,
			"words", totalWords)
	}

	return nil
}

// createParagraphRecords creates Paragraph records in DefraDB.
func (j *Job) createParagraphRecords(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	var ops []defra.WriteOp

	for _, chapter := range j.Chapters {
		if chapter.DocID == "" {
			continue
		}

		for _, para := range chapter.Paragraphs {
			// Convert edits to JSON if any
			var editsJSON string
			if len(para.EditsApplied) > 0 {
				editsBytes, err := json.Marshal(para.EditsApplied)
				if err == nil {
					editsJSON = string(editsBytes)
				}
			}

			doc := map[string]any{
				"chapter_id":    chapter.DocID,
				"sort_order":    para.SortOrder,
				"start_page":    para.StartPage,
				"raw_text":      para.RawText,
				"polished_text": para.PolishedText,
				"word_count":    para.WordCount,
			}

			if editsJSON != "" {
				doc["edits_applied"] = editsJSON
			}

			ops = append(ops, defra.WriteOp{
				Collection: "Paragraph",
				Document:   doc,
				Op:         defra.OpCreate,
			})
		}
	}

	if len(ops) == 0 {
		return nil
	}

	// Batch create paragraphs
	_, err := sink.SendManySync(ctx, ops)
	if err != nil {
		return fmt.Errorf("failed to create paragraphs: %w", err)
	}

	return nil
}
