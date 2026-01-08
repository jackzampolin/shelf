package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateExtractWorkUnits creates CPU work units for extracting text from each chapter.
func (j *Job) CreateExtractWorkUnits(ctx context.Context) ([]jobs.WorkUnit, error) {
	var units []jobs.WorkUnit

	for _, chapter := range j.Chapters {
		if chapter.ExtractDone {
			continue
		}

		unit := j.createExtractWorkUnit(chapter)
		units = append(units, unit)
	}

	j.ChaptersToExtract = len(units)
	return units, nil
}

// createExtractWorkUnit creates a single CPU work unit for text extraction.
func (j *Job) createExtractWorkUnit(chapter *ChapterState) jobs.WorkUnit {
	unitID := fmt.Sprintf("extract_%s_%s", j.Book.BookID, chapter.EntryID)

	j.Tracker.Register(unitID, WorkUnitInfo{
		UnitType:  WorkUnitTypeExtract,
		Phase:     PhaseExtract,
		ChapterID: chapter.EntryID,
	})

	return jobs.WorkUnit{
		ID:       unitID,
		Type:     jobs.WorkUnitTypeCPU,
		JobID:    j.ID(),
		Priority: 0,
		CPURequest: &jobs.CPUWorkRequest{
			Task: "extract_chapter_text",
			Data: map[string]any{
				"entry_id":   chapter.EntryID,
				"start_page": chapter.StartPage,
				"end_page":   chapter.EndPage,
			},
		},
		Metrics: j.MetricsFor(),
	}
}

// HandleExtractResult processes the result of a text extraction work unit.
func (j *Job) HandleExtractResult(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) error {
	chapter := j.GetChapterByEntryID(info.ChapterID)
	if chapter == nil {
		return fmt.Errorf("chapter not found: %s", info.ChapterID)
	}

	if !result.Success {
		j.ExtractsFailed++
		return result.Error
	}

	// The extraction is done synchronously in ExtractChapterText
	// The result is already stored in chapter state
	j.ChaptersExtracted++

	return nil
}

// ExtractChapterText extracts and cleans text for a chapter.
// This is called by the CPU worker when processing extract work units.
func (j *Job) ExtractChapterText(ctx context.Context, chapter *ChapterState) error {
	logger := svcctx.LoggerFrom(ctx)

	// Preload pages for this chapter's range
	if err := j.Book.PreloadPages(ctx, chapter.StartPage, chapter.EndPage); err != nil {
		if logger != nil {
			logger.Warn("failed to preload pages",
				"chapter", chapter.EntryID,
				"start_page", chapter.StartPage,
				"end_page", chapter.EndPage,
				"error", err)
		}
		// Continue anyway - individual page loads may still work
	}

	var pageTexts []PageText

	for pageNum := chapter.StartPage; pageNum <= chapter.EndPage; pageNum++ {
		pageData, err := j.Book.GetPageData(ctx, pageNum)
		if err != nil {
			if logger != nil {
				logger.Warn("failed to get page data",
					"page_num", pageNum,
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
			HasPageNumberInHeader: false, // Could enhance this if needed
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
