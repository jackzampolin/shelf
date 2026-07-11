package job

import (
	"context"
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// extractAllChapters extracts text for all chapters. Returns count of chapters extracted.
func (j *Job) extractAllChapters(ctx context.Context) int {
	logger := svcctx.LoggerFrom(ctx)
	chapters := j.Book.GetStructureChapters()
	chaptersExtracted := 0

	for _, chapter := range chapters {
		// Extract text from pages in range
		pageTexts := j.extractChapterPages(chapter.StartPage, chapter.EndPage)

		// Merge and clean text
		chapter.MechanicalText = common.MergeChapterPages(pageTexts)
		chapter.WordCount = common.CountWords(chapter.MechanicalText)
		chapter.ExtractDone = true
		j.Book.UpdateChapter(chapter) // Save changes back

		chaptersExtracted++
	}

	if logger != nil {
		logger.Debug("extracted chapter text",
			"book_id", j.Book.BookID,
			"chapters_extracted", chaptersExtracted)
	}

	return chaptersExtracted
}

// extractChapterPages extracts text from a range of pages.
func (j *Job) extractChapterPages(startPage, endPage int) []common.PageText {
	var pageTexts []common.PageText

	for pageNum := startPage; pageNum <= endPage; pageNum++ {
		pageState := j.Book.GetPage(pageNum)
		if pageState == nil {
			continue
		}

		// Get OCR markdown text
		ocrText := pageState.GetOcrMarkdown()
		if ocrText == "" {
			continue
		}

		header := pageState.GetHeader()
		footer := pageState.GetFooter()
		stripped := common.StripHeaderFooter(ocrText, header, footer)

		pageTexts = append(pageTexts, common.PageText{
			ScanPage:    pageNum,
			RawText:     ocrText,
			CleanedText: common.CleanPageText(stripped),
		})
	}

	return pageTexts
}

// persistExtractResults saves extract results to DefraDB with parallel direct writes.
// Extract results can be recalculated on crash recovery from page OCR data.
func (j *Job) persistExtractResults(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}
	logger := svcctx.LoggerFrom(ctx)
	chapters := j.Book.GetStructureChapters()

	var wg sync.WaitGroup
	sem := make(chan struct{}, maxPersistConcurrency)
	var mu sync.Mutex
	var firstErr error
	var count int

	for _, chapter := range chapters {
		if chapter.DocID == "" || !chapter.ExtractDone {
			continue
		}

		wg.Add(1)
		go func(ch *common.ChapterState) {
			defer wg.Done()
			sem <- struct{}{}
			defer func() { <-sem }()

			doc := chapterExtractUpdate(ch)
			result, err := defraStructureWriteWithRetry(ctx, func() (defra.WriteResult, error) {
				return defraClient.UpdateWithVersion(ctx, "Chapter", ch.DocID, doc)
			})
			if err != nil {
				mu.Lock()
				if firstErr == nil {
					firstErr = err
				}
				mu.Unlock()
				if logger != nil {
					logger.Warn("failed to persist chapter extract result",
						"chapter_id", ch.EntryID,
						"doc_id", ch.DocID,
						"error", err)
				}
				return
			}
			j.Book.TrackWrite("Chapter", ch.DocID, result.CID)
			mu.Lock()
			count++
			mu.Unlock()
		}(chapter)
	}
	wg.Wait()

	if logger != nil {
		logger.Debug("persisted extract results", "count", count)
	}
	return firstErr
}

func chapterExtractUpdate(ch *common.ChapterState) map[string]any {
	doc := map[string]any{
		"mechanical_text":  ch.MechanicalText,
		"word_count":       ch.WordCount,
		"extract_complete": true,
	}
	// A rebuilt chapter whose source text changed must not expose stale
	// polished output from the prior structure while the repair is active.
	if !ch.PolishDone {
		doc["polished_text"] = ""
		doc["edits_applied_json"] = "[]"
		doc["polish_complete"] = false
		doc["polish_failed"] = false
	}
	return doc
}
