package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ExtractAllChapters extracts text for all chapters synchronously.
// This is lightweight text processing (string manipulation, no heavy CPU work).
func (j *Job) ExtractAllChapters(ctx context.Context) error {
	logger := svcctx.LoggerFrom(ctx)

	for _, chapter := range j.Chapters {
		if chapter.ExtractDone {
			j.ChaptersExtracted++
			continue
		}

		if err := j.ExtractChapterText(ctx, chapter); err != nil {
			if logger != nil {
				logger.Warn("failed to extract chapter text",
					"chapter", chapter.EntryID,
					"error", err)
			}
			j.ExtractsFailed++
			// Continue with other chapters
		} else {
			j.ChaptersExtracted++
		}
	}

	j.ChaptersToExtract = len(j.Chapters)

	if logger != nil {
		logger.Info("extraction complete",
			"book_id", j.Book.BookID,
			"extracted", j.ChaptersExtracted,
			"failed", j.ExtractsFailed)
	}

	return nil
}

// ExtractChapterText extracts and cleans text for a single chapter.
// This is lightweight text processing - reads cached page data and performs
// string manipulation (cleaning headers, joining pages, splitting paragraphs).
func (j *Job) ExtractChapterText(ctx context.Context, chapter *ChapterState) error {
	logger := svcctx.LoggerFrom(ctx)

	// Preload pages for this chapter's range (may already be cached)
	if err := j.Book.PreloadPages(ctx, chapter.StartPage, chapter.EndPage); err != nil {
		if logger != nil {
			logger.Warn("failed to preload pages",
				"chapter", chapter.EntryID,
				"start_page", chapter.StartPage,
				"end_page", chapter.EndPage,
				"error", err)
		}
		// Continue - pages may already be cached or individual loads may work
	}

	var pageTexts []PageText

	for pageNum := chapter.StartPage; pageNum <= chapter.EndPage; pageNum++ {
		pageData, err := j.Book.GetPageData(ctx, pageNum)
		if err != nil {
			if logger != nil {
				logger.Warn("failed to get page data",
					"page_num", pageNum,
					"chapter", chapter.EntryID,
					"error", err)
			}
			continue
		}

		// Build PageData for cleaning
		cleanData := &PageData{
			ScanPage:              pageNum,
			Markdown:              pageData.BlendMarkdown,
			PrintedPage:           pageData.PageNumberLabel,
			RunningHeader:         pageData.RunningHeader,
			HasPageNumberInHeader: false,
		}

		cleaned := CleanPageText(cleanData)

		pageTexts = append(pageTexts, PageText{
			ScanPage:        pageNum,
			PrintedPage:     pageData.PageNumberLabel,
			RawText:         pageData.BlendMarkdown,
			CleanedText:     cleaned,
			RunningHeader:   pageData.RunningHeader,
			PageNumberLabel: pageData.PageNumberLabel,
		})
	}

	if len(pageTexts) == 0 {
		return fmt.Errorf("no pages extracted for chapter %s (pages %d-%d)",
			chapter.EntryID, chapter.StartPage, chapter.EndPage)
	}

	// Join pages
	mechanicalText, pageBreaks := JoinPages(pageTexts)

	// Update chapter state
	chapter.RawPageTexts = pageTexts
	chapter.MechanicalText = mechanicalText
	chapter.PageBreaks = pageBreaks

	// Split into paragraphs
	chapter.Paragraphs = SplitIntoParagraphs(mechanicalText, chapter.StartPage)

	// Calculate word count
	chapter.WordCount = len(strings.Fields(mechanicalText))

	chapter.ExtractDone = true

	if logger != nil {
		logger.Debug("extracted chapter text",
			"chapter", chapter.EntryID,
			"pages", len(pageTexts),
			"paragraphs", len(chapter.Paragraphs),
			"words", chapter.WordCount)
	}

	return nil
}

// PersistExtractResults persists extraction results to DefraDB.
func (j *Job) PersistExtractResults(ctx context.Context) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	for _, chapter := range j.Chapters {
		if !chapter.ExtractDone || chapter.DocID == "" {
			continue
		}

		// Update chapter with extracted text
		sink.Send(defra.WriteOp{
			Collection: "Chapter",
			DocID:      chapter.DocID,
			Document: map[string]any{
				"mechanical_text":  chapter.MechanicalText,
				"word_count":       chapter.WordCount,
				"extract_complete": true,
			},
			Op: defra.OpUpdate,
		})
	}

	return nil
}

// AllExtractsDone returns true if all chapters have been extracted.
func (j *Job) AllExtractsDone() bool {
	for _, ch := range j.Chapters {
		if !ch.ExtractDone {
			return false
		}
	}
	return true
}
