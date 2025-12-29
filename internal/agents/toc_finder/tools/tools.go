package tools

import (
	"context"
	"encoding/json"
	"fmt"

	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ToCFinderTools implements agent.Tools for the ToC finder agent.
type ToCFinderTools struct {
	bookID      string
	totalPages  int
	defraClient *defra.Client
	homeDir     *home.Dir

	// State
	grepReportCache   *GrepReport
	currentPageNum    *int
	currentImages     [][]byte
	pageObservations  []PageObservation
	pendingResult     *toc_finder.Result
}

// PageObservation records what the agent saw on a page.
type PageObservation struct {
	PageNum      int    `json:"page_num"`
	Observations string `json:"observations"`
}

// Config configures the ToC finder tools.
type Config struct {
	BookID      string
	TotalPages  int
	DefraClient *defra.Client
	HomeDir     *home.Dir
}

// New creates a new ToC finder tools instance.
func New(cfg Config) *ToCFinderTools {
	return &ToCFinderTools{
		bookID:           cfg.BookID,
		totalPages:       cfg.TotalPages,
		defraClient:      cfg.DefraClient,
		homeDir:          cfg.HomeDir,
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

// getPageBlendedText retrieves blended OCR text from DefraDB.
func (t *ToCFinderTools) getPageBlendedText(ctx context.Context, pageNum int) (string, error) {
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
