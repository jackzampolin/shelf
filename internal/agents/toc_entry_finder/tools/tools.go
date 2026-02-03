package tools

import (
	"context"
	"encoding/json"
	"fmt"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// TocEntryFinderTools implements agent.Tools for the ToC entry finder agent.
type TocEntryFinderTools struct {
	book  *common.BookState
	entry *toc_entry_finder.TocEntry

	// State
	currentPageNum   *int
	currentImages    [][]byte
	pageObservations []PageObservation
	pendingResult    *toc_entry_finder.Result
}

// PageObservation records what the agent saw on a page.
type PageObservation struct {
	PageNum      int    `json:"page_num"`
	Observations string `json:"observations"`
}

// Config configures the ToC entry finder tools.
type Config struct {
	Book  *common.BookState
	Entry *toc_entry_finder.TocEntry
}

// New creates a new ToC entry finder tools instance.
func New(cfg Config) *TocEntryFinderTools {
	return &TocEntryFinderTools{
		book:             cfg.Book,
		entry:            cfg.Entry,
		pageObservations: make([]PageObservation, 0),
	}
}

// GetTools returns the tool definitions for the LLM.
func (t *TocEntryFinderTools) GetTools() []providers.Tool {
	return []providers.Tool{
		getHeadingPagesTool(),
		grepTextTool(),
		getPageOcrTool(),
		loadPageImageTool(),
		writeResultTool(),
	}
}

// ExecuteTool runs a tool and returns the result as JSON.
func (t *TocEntryFinderTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
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
		return t.getHeadingPages(startPage, endPage)
	case "grep_text":
		query, _ := args["query"].(string)
		return t.grepText(ctx, query)
	case "get_page_ocr":
		pageNumF, _ := args["page_num"].(float64)
		return t.getPageOcr(ctx, int(pageNumF))
	case "load_page_image":
		pageNumF, _ := args["page_num"].(float64)
		observations, _ := args["current_page_observations"].(string)
		return t.loadPageImage(ctx, int(pageNumF), observations)
	case "write_result":
		return t.writeResult(ctx, args)
	default:
		return jsonError(fmt.Sprintf("Unknown tool: %s", name)), nil
	}
}

// IsComplete returns true when write_result has been called.
func (t *TocEntryFinderTools) IsComplete() bool {
	return t.pendingResult != nil
}

// GetImages returns the current page image for vision.
func (t *TocEntryFinderTools) GetImages() [][]byte {
	return t.currentImages
}

// GetResult returns the final result.
func (t *TocEntryFinderTools) GetResult() any {
	return t.pendingResult
}

// getPageOcrMarkdown retrieves OCR markdown text from BookState.
func (t *TocEntryFinderTools) getPageOcrMarkdown(ctx context.Context, pageNum int) (string, error) {
	text, err := t.book.GetOcrMarkdown(ctx, pageNum)
	if err != nil {
		return "", err
	}
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
