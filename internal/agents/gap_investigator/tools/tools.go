package tools

import (
	"context"
	"encoding/json"
	"fmt"

	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/providers"
)

// GapInvestigatorTools implements agent.Tools for the gap investigator agent.
type GapInvestigatorTools struct {
	bookID         string
	totalPages     int
	defraClient    *defra.Client
	homeDir        *home.Dir
	gap            *gap_investigator.GapInfo
	linkedEntries  []*gap_investigator.LinkedEntry
	bodyStart      int
	bodyEnd        int

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
	BookID        string
	TotalPages    int
	DefraClient   *defra.Client
	HomeDir       *home.Dir
	Gap           *gap_investigator.GapInfo
	LinkedEntries []*gap_investigator.LinkedEntry
	BodyStart     int
	BodyEnd       int
}

// New creates a new gap investigator tools instance.
func New(cfg Config) *GapInvestigatorTools {
	return &GapInvestigatorTools{
		bookID:           cfg.BookID,
		totalPages:       cfg.TotalPages,
		defraClient:      cfg.DefraClient,
		homeDir:          cfg.HomeDir,
		gap:              cfg.Gap,
		linkedEntries:    cfg.LinkedEntries,
		bodyStart:        cfg.BodyStart,
		bodyEnd:          cfg.BodyEnd,
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
		pageNumF, _ := args["page_num"].(float64)
		return t.getPageOcr(ctx, int(pageNumF))
	case "load_page_image":
		pageNumF, _ := args["page_num"].(float64)
		observations, _ := args["current_page_observations"].(string)
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

// getPageBlendedText retrieves blended OCR text from DefraDB.
func (t *GapInvestigatorTools) getPageBlendedText(ctx context.Context, pageNum int) (string, error) {
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
