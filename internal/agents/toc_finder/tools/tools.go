package tools

import (
	"context"
	"encoding/json"
	"fmt"

	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ToCFinderTools implements agent.Tools for the ToC finder agent.
type ToCFinderTools struct {
	book *common.BookState

	// State
	grepReportCache  *GrepReport
	currentPageNum   *int
	currentImages    [][]byte
	pageObservations []PageObservation
	pendingResult    *toc_finder.Result
}

// PageObservation records what the agent saw on a page.
type PageObservation struct {
	PageNum      int    `json:"page_num"`
	Observations string `json:"observations"`
}

// Config configures the ToC finder tools.
type Config struct {
	Book *common.BookState
}

// New creates a new ToC finder tools instance.
func New(cfg Config) *ToCFinderTools {
	return &ToCFinderTools{
		book:             cfg.Book,
		pageObservations: make([]PageObservation, 0),
	}
}

// GetTools returns the tool definitions for the LLM.
func (t *ToCFinderTools) GetTools() []providers.Tool {
	return []providers.Tool{
		grepReportTool(),
		loadPageImageTool(),
		loadOcrTextTool(),
		writeTocResultTool(),
	}
}

// ExecuteTool runs a tool and returns the result as JSON.
func (t *ToCFinderTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
	switch name {
	case "get_frontmatter_grep_report":
		return t.getFrontmatterGrepReport(ctx)
	case "load_page_image":
		pageNum, _ := args["page_num"].(float64)
		observations, _ := args["current_page_observations"].(string)
		return t.loadPageImage(ctx, int(pageNum), observations)
	case "load_ocr_text":
		return t.loadOcrText(ctx)
	case "write_toc_result":
		return t.writeTocResult(ctx, args)
	default:
		return jsonError(fmt.Sprintf("Unknown tool: %s", name)), nil
	}
}

// IsComplete returns true when write_toc_result has been called.
func (t *ToCFinderTools) IsComplete() bool {
	return t.pendingResult != nil
}

// GetImages returns the current page image for vision.
func (t *ToCFinderTools) GetImages() [][]byte {
	return t.currentImages
}

// GetResult returns the final result.
func (t *ToCFinderTools) GetResult() any {
	return t.pendingResult
}

// getPageOcrMarkdown retrieves OCR markdown text from BookState.
func (t *ToCFinderTools) getPageOcrMarkdown(ctx context.Context, pageNum int) (string, error) {
	page := t.book.GetPage(pageNum)
	if page == nil {
		return "", fmt.Errorf("page %d not in state", pageNum)
	}

	text := page.GetOcrMarkdown()
	if text == "" {
		return "", fmt.Errorf("no ocr markdown for page %d", pageNum)
	}

	return text, nil
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
func mustMarshal(v any) json.RawMessage {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}
