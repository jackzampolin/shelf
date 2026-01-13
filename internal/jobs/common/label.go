package common

import (
	"context"
	"fmt"
	"strconv"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// loadBlendedTextFromDB loads blend_markdown for a single page from DefraDB.
// Use this when in-memory cache is empty (e.g., after job reload).
func loadBlendedTextFromDB(ctx context.Context, bookID string, pageNum int) string {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return ""
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_eq: %d}}) {
			blend_markdown
		}
	}`, bookID, pageNum)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return ""
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return ""
	}

	page, ok := pages[0].(map[string]any)
	if !ok {
		return ""
	}

	blendMarkdown, _ := page["blend_markdown"].(string)
	return blendMarkdown
}

// BuildPatternContext builds pattern context for a page from pattern analysis results.
// Returns nil if pattern analysis is not complete or not available.
func BuildPatternContext(book *BookState, pageNum int) *label.PatternContext {
	result := book.GetPatternAnalysisResult()
	if result == nil {
		return nil
	}
	ctx := &label.PatternContext{}

	// Build page number context
	if result.PageNumberPattern != nil {
		pattern := result.PageNumberPattern
		ctx.PageNumberLocation = pattern.Location
		ctx.PageNumberPosition = pattern.Position
		ctx.PageNumberFormat = pattern.Format

		// Calculate expected page number if this page is in the numbered range
		if pageNum >= pattern.StartPage && (pattern.EndPage == nil || pageNum <= *pattern.EndPage) {
			// Check if page is in a gap range
			inGap := false
			for _, gap := range pattern.GapRanges {
				if pageNum >= gap.StartPage && pageNum <= gap.EndPage {
					ctx.InPageNumberGap = true
					ctx.PageNumberGapReason = gap.Reason
					inGap = true
					break
				}
			}

			if !inGap {
				// Calculate expected page number based on offset from start
				offset := pageNum - pattern.StartPage
				expectedNum := pattern.StartValue + offset
				expectedStr := strconv.Itoa(expectedNum)
				ctx.ExpectedPageNumber = &expectedStr
			}
		}
	}

	// Build running header context from chapter patterns
	if len(result.ChapterPatterns) > 0 {
		for _, chPattern := range result.ChapterPatterns {
			if pageNum >= chPattern.StartPage && pageNum <= chPattern.EndPage {
				ctx.InRunningHeaderCluster = true
				ctx.ExpectedRunningHeader = &chPattern.RunningHeader

				// Check if this page is near a chapter boundary (within 2 pages)
				if pageNum <= chPattern.StartPage+2 || pageNum >= chPattern.EndPage-2 {
					ctx.NearChapterBoundary = true
					if chPattern.ChapterNumber != nil {
						numStr := strconv.Itoa(*chPattern.ChapterNumber)
						ctx.ExpectedChapterNumber = &numStr
					}
					ctx.ExpectedChapterTitle = &chPattern.ChapterTitle
				}
				break
			}
		}
	}

	// Build content type hints from body boundaries
	if result.BodyBoundaries != nil {
		boundaries := result.BodyBoundaries
		ctx.BodyStartPage = boundaries.BodyStartPage
		if boundaries.BodyEndPage != nil {
			ctx.BodyEndPage = *boundaries.BodyEndPage
		}

		if pageNum < boundaries.BodyStartPage {
			ctx.ContentTypeHint = "front_matter"
			ctx.IsInBodyRange = false
		} else if boundaries.BodyEndPage != nil && pageNum > *boundaries.BodyEndPage {
			ctx.ContentTypeHint = "back_matter"
			ctx.IsInBodyRange = false
		} else {
			ctx.ContentTypeHint = "body"
			ctx.IsInBodyRange = true
		}
	}

	return ctx
}

// CreateLabelWorkUnit creates a label extraction LLM work unit.
// Returns nil if no blended text is available.
// The caller is responsible for registering the work unit with their tracker.
func CreateLabelWorkUnit(ctx context.Context, jc JobContext, pageNum int, state *PageState) (*jobs.WorkUnit, string) {
	book := jc.GetBook()
	logger := svcctx.LoggerFrom(ctx)

	// Get blended text from BookState (written through from blend stage)
	blendedText := state.GetBlendedText()

	// Fall back to DB if in-memory state doesn't have blend_markdown cached
	// (happens after job reload)
	if blendedText == "" {
		blendedText = loadBlendedTextFromDB(ctx, book.BookID, pageNum)
	}

	if blendedText == "" {
		if logger != nil {
			logger.Debug("cannot create label work unit: no blended text in state or DB",
				"page_num", pageNum)
		}
		return nil, ""
	}

	unitID := uuid.New().String()

	// Build pattern context if pattern analysis is complete
	patternContext := BuildPatternContext(book, pageNum)

	unit := label.CreateWorkUnit(label.Input{
		BlendedText:          blendedText,
		PageNum:              pageNum,
		PatternContext:       patternContext,
		SystemPromptOverride: book.GetPrompt(label.SystemPromptKey),
		UserPromptOverride:   book.GetPrompt(label.UserPromptKey),
	})
	unit.ID = unitID
	unit.Provider = book.LabelProvider
	unit.JobID = jc.ID()
	unit.Priority = jobs.PriorityForStage("label")

	unit.Metrics = &jobs.WorkUnitMetrics{
		BookID:    book.BookID,
		Stage:     "label",
		ItemKey:   fmt.Sprintf("page_%04d_label", pageNum),
		PromptKey: label.SystemPromptKey,
		PromptCID: book.GetPromptCID(label.SystemPromptKey),
	}

	return unit, unitID
}

// SaveLabelResult parses the label result, persists to DefraDB, and updates page state (thread-safe).
func SaveLabelResult(ctx context.Context, state *PageState, parsedJSON any) error {
	labelResult, err := label.ParseResult(parsedJSON)
	if err != nil {
		return err
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{
		"label_complete":   true,
		"content_type":     labelResult.ContentType,
		"is_chapter_start": labelResult.IsChapterStart,
		"is_blank_page":    labelResult.IsBlankPage,
		"has_footnotes":    labelResult.HasFootnotes,
	}

	if labelResult.PageNumber != nil {
		update["page_number_label"] = *labelResult.PageNumber
	}
	if labelResult.RunningHeader != nil {
		update["running_header"] = *labelResult.RunningHeader
	}
	if labelResult.ChapterNumber != nil {
		update["chapter_number"] = *labelResult.ChapterNumber
	}
	if labelResult.ChapterTitle != nil {
		update["chapter_title"] = *labelResult.ChapterTitle
	}

	// Set deprecated fields based on content_type for backwards compatibility
	switch labelResult.ContentType {
	case "toc":
		update["is_toc_page"] = true
	case "front_matter", "title_page", "copyright":
		update["is_front_matter"] = true
	case "back_matter":
		update["is_back_matter"] = true
	}

	// Fire-and-forget write - sink batches and logs errors internally
	sink.Send(defra.WriteOp{
		Collection: "Page",
		DocID:      state.GetPageDocID(),
		Document:   update,
		Op:         defra.OpUpdate,
	})

	// Write-through: Update in-memory cache with all persisted data (thread-safe)
	state.SetLabelResultCached(labelResult.PageNumber, labelResult.RunningHeader)

	return nil
}
