package tools

import (
	"context"
	"encoding/json"
	"fmt"

	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/providers"
)

// GapInvestigatorTools implements agent.Tools for the gap investigator agent.
type GapInvestigatorTools struct {
	book          *common.BookState
	gap           *gap_investigator.GapInfo
	linkedEntries []*gap_investigator.LinkedEntry

	// State
	currentPageNum   *int
	currentImages    [][]byte
	pageObservations []PageObservation
	pendingResult    *gap_investigator.Result
}

// PageObservation records what the agent saw on a page.
type PageObservation struct {
	PageNum      int    `json:"page_num"`
	Observations string `json:"observations"`
}

// Config configures the gap investigator tools.
type Config struct {
	Book          *common.BookState
	Gap           *gap_investigator.GapInfo
	LinkedEntries []*gap_investigator.LinkedEntry
}

// New creates a new gap investigator tools instance.
func New(cfg Config) *GapInvestigatorTools {
	return &GapInvestigatorTools{
		book:             cfg.Book,
		gap:              cfg.Gap,
		linkedEntries:    cfg.LinkedEntries,
		pageObservations: make([]PageObservation, 0),
	}
}

// GetTools returns the tool definitions for the LLM.
func (t *GapInvestigatorTools) GetTools() []providers.Tool {
	return []providers.Tool{
		getGapContextTool(),
		getPageOcrTool(),
		loadPageImageTool(),
		writeFixTool(),
	}
}

// ExecuteTool runs a tool and returns the result as JSON.
func (t *GapInvestigatorTools) ExecuteTool(ctx context.Context, name string, args map[string]any) (string, error) {
	switch name {
	case "get_gap_context":
		return t.getGapContext(ctx)
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
	case "write_fix":
		return t.writeFix(ctx, args)
	default:
		return jsonError(fmt.Sprintf("Unknown tool: %s", name)), nil
	}
}

// IsComplete returns true when write_fix has been called.
func (t *GapInvestigatorTools) IsComplete() bool {
	return t.pendingResult != nil
}

// GetImages returns the current page image for vision.
func (t *GapInvestigatorTools) GetImages() [][]byte {
	return t.currentImages
}

// GetResult returns the final result.
func (t *GapInvestigatorTools) GetResult() any {
	return t.pendingResult
}

// getPageOcrMarkdown retrieves OCR markdown text from BookState.
func (t *GapInvestigatorTools) getPageOcrMarkdown(ctx context.Context, pageNum int) (string, error) {
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
// Used for static tool schemas - failure indicates a programming bug.
func mustMarshal(v any) json.RawMessage {
	b, err := json.Marshal(v)
	if err != nil {
		panic(err)
	}
	return b
}
