package common

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/google/uuid"

	page_pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/page_pattern_analyzer"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// blendedPage holds page number and blend_markdown loaded from DB.
type blendedPage struct {
	PageNum       int
	BlendMarkdown string
}

// loadBlendedPagesFromDB loads blend_markdown for all blended pages from DefraDB.
// Use this when in-memory cache is empty (e.g., after job reload).
func loadBlendedPagesFromDB(ctx context.Context, bookID string) ([]blendedPage, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, blend_complete: {_eq: true}}, order: {page_num: ASC}) {
			page_num
			blend_markdown
		}
	}`, bookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return nil, err
	}

	pagesData, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil, nil
	}

	var pages []blendedPage
	for _, p := range pagesData {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}
		blendMarkdown, _ := page["blend_markdown"].(string)

		if pageNum > 0 && blendMarkdown != "" {
			pages = append(pages, blendedPage{
				PageNum:       pageNum,
				BlendMarkdown: blendMarkdown,
			})
		}
	}

	return pages, nil
}

// ExtractPageLines extracts non-empty lines from markdown for pattern analysis.
// Returns the first 2 and last 2 non-empty, non-heading lines (or fewer if page has less content).
// Markdown headings are excluded because they represent structural markers, not running headers
// or page numbers (which appear in plain text at page margins).
// Returns (firstLines []string, lastLines []string) where each slice contains 0-2 lines.
func ExtractPageLines(markdown string) (firstLines, lastLines []string) {
	lines := strings.Split(markdown, "\n")
	var nonEmpty []string

	// Collect non-empty lines that aren't headings
	for _, line := range lines {
		trimmed := strings.TrimSpace(line)
		if trimmed != "" && !strings.HasPrefix(trimmed, "#") {
			nonEmpty = append(nonEmpty, trimmed)
		}
	}

	// Extract first 2 lines
	for i := 0; i < 2 && i < len(nonEmpty); i++ {
		firstLines = append(firstLines, nonEmpty[i])
	}

	// Extract last 2 lines
	start := len(nonEmpty) - 2
	if start < 0 {
		start = 0
	}
	for i := start; i < len(nonEmpty); i++ {
		lastLines = append(lastLines, nonEmpty[i])
	}

	return firstLines, lastLines
}

// CreatePageNumberPatternWorkUnit creates a work unit to detect page numbering patterns.
// Analyzes last lines from all pages to find numbering location, format, and sequences.
func CreatePageNumberPatternWorkUnit(ctx context.Context, jc JobContext) (*jobs.WorkUnit, string) {
	book := jc.GetBook()

	// Load blend_markdown from DB for all blended pages
	// (in-memory cache may be empty after job reload)
	blendedPages, err := loadBlendedPagesFromDB(ctx, book.BookID)
	if err != nil {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("failed to load blended pages from DB", "error", err)
		}
		return nil, ""
	}

	// Collect page line data from all pages
	var pages []page_pattern_analyzer.PageLineData
	for _, bp := range blendedPages {
		_, lastLines := ExtractPageLines(bp.BlendMarkdown)
		pages = append(pages, page_pattern_analyzer.PageLineData{
			PageNum:   bp.PageNum,
			LastLines: lastLines,
		})
	}

	if len(pages) == 0 {
		return nil, ""
	}

	unitID := uuid.New().String()

	// Build user prompt data
	data := page_pattern_analyzer.UserPromptData{
		Pages:      pages,
		TotalPages: book.TotalPages,
	}

	userPrompt := page_pattern_analyzer.UserPageNumbersPromptWithOverride(
		data,
		book.GetPrompt(page_pattern_analyzer.UserPageNumbersKey),
	)

	systemPrompt := book.GetPrompt(page_pattern_analyzer.SystemPageNumbersKey)
	if systemPrompt == "" {
		systemPrompt = page_pattern_analyzer.SystemPageNumbersPrompt()
	}

	// Build JSON schema
	jsonSchema, err := json.Marshal(page_pattern_analyzer.PageNumberPatternSchema()["json_schema"])
	if err != nil {
		// This is a programming error - the schema structure is malformed
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Error("BUG: failed to marshal page number pattern schema", "error", err)
		}
		return nil, ""
	}

	unit := &jobs.WorkUnit{
		ID:   unitID,
		Type: jobs.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{
			Messages: []providers.Message{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userPrompt},
			},
			ResponseFormat: &providers.ResponseFormat{
				Type:       "json_schema",
				JSONSchema: jsonSchema,
			},
			Temperature: 0.1,
			MaxTokens:   4096,
		},
		Provider: book.TocProvider, // Use same provider as ToC operations
		JobID:    jc.ID(),
		Priority: jobs.PriorityForStage("pattern_analysis"),
		Metrics: &jobs.WorkUnitMetrics{
			BookID:    book.BookID,
			Stage:     "pattern_analysis",
			ItemKey:   "page_number_pattern",
			PromptKey: page_pattern_analyzer.SystemPageNumbersKey,
			PromptCID: book.GetPromptCID(page_pattern_analyzer.SystemPageNumbersKey),
		},
	}

	return unit, unitID
}

// CreateChapterPatternsWorkUnit creates a work unit to detect chapter patterns.
// Analyzes first lines from all pages to find running header clusters.
func CreateChapterPatternsWorkUnit(ctx context.Context, jc JobContext) (*jobs.WorkUnit, string) {
	book := jc.GetBook()

	// Load blend_markdown from DB for all blended pages
	// (in-memory cache may be empty after job reload)
	blendedPages, err := loadBlendedPagesFromDB(ctx, book.BookID)
	if err != nil {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("failed to load blended pages from DB", "error", err)
		}
		return nil, ""
	}

	// Collect page line data from all pages
	var pages []page_pattern_analyzer.PageLineData
	for _, bp := range blendedPages {
		firstLines, _ := ExtractPageLines(bp.BlendMarkdown)
		pages = append(pages, page_pattern_analyzer.PageLineData{
			PageNum:    bp.PageNum,
			FirstLines: firstLines,
		})
	}

	if len(pages) == 0 {
		return nil, ""
	}

	unitID := uuid.New().String()

	// Build user prompt data
	data := page_pattern_analyzer.UserPromptData{
		Pages:      pages,
		TotalPages: book.TotalPages,
	}

	userPrompt := page_pattern_analyzer.UserChaptersPromptWithOverride(
		data,
		book.GetPrompt(page_pattern_analyzer.UserChaptersKey),
	)

	systemPrompt := book.GetPrompt(page_pattern_analyzer.SystemChaptersKey)
	if systemPrompt == "" {
		systemPrompt = page_pattern_analyzer.SystemChaptersPrompt()
	}

	// Build JSON schema
	jsonSchema, err := json.Marshal(page_pattern_analyzer.ChapterPatternsSchema()["json_schema"])
	if err != nil {
		// This is a programming error - the schema structure is malformed
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Error("BUG: failed to marshal chapter patterns schema", "error", err)
		}
		return nil, ""
	}

	unit := &jobs.WorkUnit{
		ID:   unitID,
		Type: jobs.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{
			Messages: []providers.Message{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userPrompt},
			},
			ResponseFormat: &providers.ResponseFormat{
				Type:       "json_schema",
				JSONSchema: jsonSchema,
			},
			Temperature: 0.1,
			MaxTokens:   4096,
		},
		Provider: book.TocProvider,
		JobID:    jc.ID(),
		Priority: jobs.PriorityForStage("pattern_analysis"),
		Metrics: &jobs.WorkUnitMetrics{
			BookID:    book.BookID,
			Stage:     "pattern_analysis",
			ItemKey:   "chapter_patterns",
			PromptKey: page_pattern_analyzer.SystemChaptersKey,
			PromptCID: book.GetPromptCID(page_pattern_analyzer.SystemChaptersKey),
		},
	}

	return unit, unitID
}

// CreateBodyBoundariesWorkUnit creates a work unit to detect body boundaries.
// Uses page number pattern and chapter pattern results as input.
func CreateBodyBoundariesWorkUnit(
	ctx context.Context,
	jc JobContext,
	pageNumberPattern *page_pattern_analyzer.PageNumberPattern,
	chapterPatterns []page_pattern_analyzer.ChapterPattern,
) (*jobs.WorkUnit, string) {
	book := jc.GetBook()

	unitID := uuid.New().String()

	// Build user prompt data
	data := page_pattern_analyzer.BoundariesPromptData{
		PageNumberPattern: pageNumberPattern,
		ChapterPatterns:   chapterPatterns,
		TotalPages:        book.TotalPages,
	}

	userPrompt := page_pattern_analyzer.UserBoundariesPromptWithOverride(
		data,
		book.GetPrompt(page_pattern_analyzer.UserBoundariesKey),
	)

	systemPrompt := book.GetPrompt(page_pattern_analyzer.SystemBoundariesKey)
	if systemPrompt == "" {
		systemPrompt = page_pattern_analyzer.SystemBoundariesPrompt()
	}

	// Build JSON schema
	jsonSchema, err := json.Marshal(page_pattern_analyzer.BodyBoundariesSchema()["json_schema"])
	if err != nil {
		// This is a programming error - the schema structure is malformed
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Error("BUG: failed to marshal body boundaries schema", "error", err)
		}
		return nil, ""
	}

	unit := &jobs.WorkUnit{
		ID:   unitID,
		Type: jobs.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{
			Messages: []providers.Message{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userPrompt},
			},
			ResponseFormat: &providers.ResponseFormat{
				Type:       "json_schema",
				JSONSchema: jsonSchema,
			},
			Temperature: 0.1,
			MaxTokens:   4096,
		},
		Provider: book.TocProvider,
		JobID:    jc.ID(),
		Priority: jobs.PriorityForStage("pattern_analysis"),
		Metrics: &jobs.WorkUnitMetrics{
			BookID:    book.BookID,
			Stage:     "pattern_analysis",
			ItemKey:   "body_boundaries",
			PromptKey: page_pattern_analyzer.SystemBoundariesKey,
			PromptCID: book.GetPromptCID(page_pattern_analyzer.SystemBoundariesKey),
		},
	}

	return unit, unitID
}

// SavePatternAnalysisResult persists the complete pattern analysis result to DefraDB.
func SavePatternAnalysisResult(ctx context.Context, bookDocID string, result *page_pattern_analyzer.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Marshal result to JSON
	resultJSON, err := json.Marshal(result)
	if err != nil {
		return fmt.Errorf("failed to marshal pattern analysis result: %w", err)
	}

	// Persist to Book record
	sink.Send(defra.WriteOp{
		Collection: "Book",
		DocID:      bookDocID,
		Document: map[string]any{
			"page_pattern_analysis_json": string(resultJSON),
		},
		Op: defra.OpUpdate,
	})

	return nil
}
