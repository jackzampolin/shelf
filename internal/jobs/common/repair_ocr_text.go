package common

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

const OperatorVerifiedOCRProvider = "operator-verified"

type OCRTextRepairResult struct {
	Page           int
	Characters     int
	DeletedResults int
}

// RepairOCRTextPage replaces failed image OCR with a source-verified
// transcription. It is deliberately operator-invoked and requires a durable
// reason so blank leaves, maps, and other pathological pages are represented
// explicitly instead of silently skipped or accepted as degraded output.
func RepairOCRTextPage(ctx context.Context, book *BookState, pageNum int, text, reason string) (*OCRTextRepairResult, error) {
	if book == nil {
		return nil, fmt.Errorf("book is required")
	}
	if book.Store == nil {
		return nil, fmt.Errorf("book state store is required")
	}
	text = strings.TrimSpace(text)
	reason = strings.TrimSpace(reason)
	if text == "" {
		return nil, fmt.Errorf("verified text is required; describe a source-blank page explicitly")
	}
	if reason == "" {
		return nil, fmt.Errorf("source verification reason is required")
	}
	pages, err := normalizeRepairPages([]int{pageNum}, book.TotalPages)
	if err != nil {
		return nil, err
	}
	pageNum = pages[0]
	state := book.GetPage(pageNum)
	if state == nil {
		return nil, fmt.Errorf("page %d is not present in durable book state", pageNum)
	}
	pageDocID := state.GetPageDocID()
	if pageDocID == "" {
		return nil, fmt.Errorf("page %d has no durable document ID", pageNum)
	}

	query := fmt.Sprintf(`{
		OcrResult(filter: {_pageID: {_eq: "%s"}}) {
			_docID
		}
	}`, pageDocID)
	resp, err := book.Store.Execute(ctx, query, nil)
	if err != nil {
		return nil, fmt.Errorf("query prior OCR results for page %d: %w", pageNum, err)
	}
	if errMsg := resp.Error(); errMsg != "" {
		return nil, fmt.Errorf("query prior OCR results for page %d: %s", pageNum, errMsg)
	}

	deleteOps := make([]defra.WriteOp, 0)
	if results, ok := resp.Data["OcrResult"].([]any); ok {
		for _, raw := range results {
			result, ok := raw.(map[string]any)
			if !ok {
				continue
			}
			resultID, _ := result["_docID"].(string)
			if resultID != "" {
				deleteOps = append(deleteOps, defra.WriteOp{
					Collection: "OcrResult",
					DocID:      resultID,
					Op:         defra.OpDelete,
					Source:     "RepairOCRTextPage:delete_prior",
				})
			}
		}
	}

	headings := ExtractHeadings(text)
	headingsJSON, err := json.Marshal(headings)
	if err != nil {
		return nil, fmt.Errorf("marshal headings for page %d: %w", pageNum, err)
	}
	ops := make([]defra.WriteOp, 0, len(deleteOps)+2)
	ops = append(ops, deleteOps...)
	ops = append(ops,
		defra.WriteOp{
			Collection: "OcrResult",
			Document: map[string]any{
				"_pageID":  pageDocID,
				"provider": OperatorVerifiedOCRProvider,
				"text":     text,
				"provider_metadata": map[string]any{
					"source": "operator_verified_source_page",
					"reason": reason,
				},
			},
			Op:     defra.OpCreate,
			Source: "RepairOCRTextPage:create_result",
		},
		defra.WriteOp{
			Collection: "Page",
			DocID:      pageDocID,
			Document: map[string]any{
				"ocr_complete":          true,
				"ocr_markdown":          text,
				"headings":              string(headingsJSON),
				"header":                nil,
				"footer":                nil,
				"ocr_quarantined":       false,
				"ocr_quarantine_reason": nil,
			},
			Op:     defra.OpUpdate,
			Source: "RepairOCRTextPage:update_page",
		},
	)
	results, err := book.Store.SendManySync(ctx, ops)
	if err != nil {
		return nil, fmt.Errorf("persist verified OCR text: %w", err)
	}
	for i, result := range results {
		if result.Err != nil {
			return nil, fmt.Errorf("persist verified OCR operation %d for %s: %w", i, result.DocID, result.Err)
		}
	}

	state.ResetOcrProviders(book.OcrProviders)
	state.ClearOCRQuarantine()
	state.SetOcrMarkdownWithHeadings(text, headings)
	state.SetOCRComplete(true)
	return &OCRTextRepairResult{Page: pageNum, Characters: len(text), DeletedResults: len(deleteOps)}, nil
}
