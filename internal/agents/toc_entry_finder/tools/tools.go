package tools

import (
	"context"
	"encoding/json"
	"fmt"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/providers"
)

// TocEntryFinderTools implements agent.Tools for the ToC entry finder agent.
type TocEntryFinderTools struct {
	bookID      string
	totalPages  int
	defraClient *defra.Client
	homeDir     *home.Dir
	entry       *toc_entry_finder.TocEntry

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
	BookID      string
	TotalPages  int
	DefraClient *defra.Client
	HomeDir     *home.Dir
	Entry       *toc_entry_finder.TocEntry
}

// New creates a new ToC entry finder tools instance.
func New(cfg Config) *TocEntryFinderTools {
	return &TocEntryFinderTools{
		bookID:           cfg.BookID,
		totalPages:       cfg.TotalPages,
		defraClient:      cfg.DefraClient,
		homeDir:          cfg.HomeDir,
		entry:            cfg.Entry,
		pageObservations: make([]PageObservation, 0),
	}
}

// GetTools returns the tool definitions for the LLM.
func (t *TocEntryFinderTools) GetTools() []providers.Tool {
	return []providers.Tool{
		grepTextTool(),
		getPageOcrTool(),
		loadPageImageTool(),
		writeResultTool(),
	}
}

// ExecuteTool runs a tool and returns the result as JSON.
func (t *TocEntryFinderTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
	switch name {
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

// getPageBlendedText retrieves blended OCR text from DefraDB.
func (t *TocEntryFinderTools) getPageBlendedText(ctx context.Context, pageNum int) (string, error) {
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
