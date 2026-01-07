package tools

import (
	"context"
	"encoding/json"
	"fmt"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ChapterFinderTools implements agent.Tools for the chapter finder agent.
type ChapterFinderTools struct {
	bookID         string
	totalPages     int
	defraClient    *defra.Client
	homeDir        *home.Dir
	entry          *chapter_finder.EntryToFind
	excludedRanges []chapter_finder.ExcludedRange

	// State
	currentPageNum   *int
	currentImages    [][]byte
	pageObservations []PageObservation
	pendingResult    *chapter_finder.Result
}

// PageObservation records what the agent saw on a page.
type PageObservation struct {
	PageNum      int    `json:"page_num"`
	Observations string `json:"observations"`
}

// Config configures the chapter finder tools.
type Config struct {
	BookID         string
	TotalPages     int
	DefraClient    *defra.Client
	HomeDir        *home.Dir
	Entry          *chapter_finder.EntryToFind
	ExcludedRanges []chapter_finder.ExcludedRange
}

// New creates a new chapter finder tools instance.
func New(cfg Config) *ChapterFinderTools {
	return &ChapterFinderTools{
		bookID:           cfg.BookID,
		totalPages:       cfg.TotalPages,
		defraClient:      cfg.DefraClient,
		homeDir:          cfg.HomeDir,
		entry:            cfg.Entry,
		excludedRanges:   cfg.ExcludedRanges,
		pageObservations: make([]PageObservation, 0),
	}
}

// GetTools returns the tool definitions for the LLM.
func (t *ChapterFinderTools) GetTools() []providers.Tool {
	return []providers.Tool{
		getHeadingPagesTool(),
		grepTextTool(),
		getPageOcrTool(),
		loadPageImageTool(),
		writeResultTool(),
	}
}

// ExecuteTool runs a tool and returns the result as JSON.
func (t *ChapterFinderTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
	switch name {
	case "get_heading_pages":
		var startPage, endPage *int
		if sp, ok := args["start_page"].(float64); ok {
			i := int(sp)
			startPage = &i
		}
		if ep, ok := args["end_page"].(float64); ok {
			i := int(ep)
			endPage = &i
		}
		return t.getHeadingPages(ctx, startPage, endPage)
	case "grep_text":
		query, ok := args["query"].(string)
		if !ok {
			return jsonError("missing or invalid 'query' parameter"), nil
		}
		return t.grepText(ctx, query)
	case "get_page_ocr":
		pageNumF, ok := args["page_num"].(float64)
		if !ok {
			return jsonError("missing or invalid 'page_num' parameter"), nil
		}
		return t.getPageOcr(ctx, int(pageNumF))
	case "load_page_image":
		pageNumF, ok := args["page_num"].(float64)
		if !ok {
			return jsonError("missing or invalid 'page_num' parameter"), nil
		}
		observations, _ := args["current_page_observations"].(string) // Optional parameter
		return t.loadPageImage(ctx, int(pageNumF), observations)
	case "write_result":
		return t.writeResult(ctx, args)
	default:
		return jsonError(fmt.Sprintf("Unknown tool: %s", name)), nil
	}
}

// IsComplete returns true when write_result has been called.
func (t *ChapterFinderTools) IsComplete() bool {
	return t.pendingResult != nil
}

// GetImages returns the current page image for vision.
func (t *ChapterFinderTools) GetImages() [][]byte {
	return t.currentImages
}

// GetResult returns the final result.
func (t *ChapterFinderTools) GetResult() any {
	return t.pendingResult
}

// getPageBlendedText retrieves blended OCR text from DefraDB.
func (t *ChapterFinderTools) getPageBlendedText(ctx context.Context, pageNum int) (string, error) {
	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_eq: %d}}) {
			blend_markdown
		}
	}`, t.bookID, pageNum)

	resp, err := t.defraClient.Execute(ctx, query, nil)
	if err != nil {
		return "", err
	}

	if errMsg := resp.Error(); errMsg != "" {
		return "", fmt.Errorf("query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok || len(pages) == 0 {
		return "", fmt.Errorf("page not found")
	}

	page, ok := pages[0].(map[string]any)
	if !ok {
		return "", fmt.Errorf("invalid page format")
	}

	text, ok := page["blend_markdown"].(string)
	if !ok || text == "" {
		return "", fmt.Errorf("no blended text")
	}

	return text, nil
}

// isInExcludedRange checks if a page is in an excluded range.
func (t *ChapterFinderTools) isInExcludedRange(pageNum int) bool {
	for _, ex := range t.excludedRanges {
		if pageNum >= ex.StartPage && pageNum <= ex.EndPage {
			return true
		}
	}
	return false
}

// Helper functions for JSON responses
func jsonSuccess(data map[string]any) string {
	data["success"] = true
	b, _ := json.MarshalIndent(data, "", "  ")
	return string(b)
}

func jsonError(msg string) string {
	b, _ := json.Marshal(map[string]any{"error": msg})
	return string(b)
}

// mustMarshal marshals a value to JSON, panicking on error.
// Used for static tool schemas - failure indicates a programming bug.
func mustMarshal(v any) json.RawMessage {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}
