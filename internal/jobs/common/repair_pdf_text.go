package common

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
	"strings"

	"github.com/jackzampolin/shelf/internal/defra"
)

const PDFTextProvider = "pdf-text"

type PDFTextRepairResult struct {
	Pages          []int
	Characters     int
	DeletedResults int
}

// RepairPDFTextPages replaces image OCR for selected pages with the PDF's real
// embedded text layer. This is intentionally operator-invoked: image-only scans
// continue through configured OCR providers, while known text-native pages can
// be repaired without truncating or inventing content.
func RepairPDFTextPages(ctx context.Context, book *BookState, pageNums []int, minChars int) (*PDFTextRepairResult, error) {
	if book == nil {
		return nil, fmt.Errorf("book is required")
	}
	if book.Store == nil {
		return nil, fmt.Errorf("book state store is required")
	}
	if minChars < 1 {
		return nil, fmt.Errorf("minimum characters must be positive")
	}
	pages, err := normalizeRepairPages(pageNums, book.TotalPages)
	if err != nil {
		return nil, err
	}

	type repairedPage struct {
		pageNum  int
		state    *PageState
		docID    string
		text     string
		headings []HeadingItem
	}
	repaired := make([]repairedPage, 0, len(pages))
	deleteOps := make([]defra.WriteOp, 0)
	totalChars := 0

	// Finish every source read before mutating durable state.
	for _, pageNum := range pages {
		state := book.GetPage(pageNum)
		if state == nil {
			return nil, fmt.Errorf("page %d is not present in durable book state", pageNum)
		}
		docID := state.GetPageDocID()
		if docID == "" {
			return nil, fmt.Errorf("page %d has no durable document ID", pageNum)
		}
		pdfPath, pageInPDF := book.PDFs.FindPDFForPage(pageNum)
		if pdfPath == "" || pageInPDF == 0 {
			return nil, fmt.Errorf("page %d has no source PDF mapping", pageNum)
		}
		text, err := extractEmbeddedPDFText(ctx, pdfPath, pageInPDF)
		if err != nil {
			return nil, fmt.Errorf("extract embedded text for page %d: %w", pageNum, err)
		}
		if len(text) < minChars {
			return nil, fmt.Errorf("page %d embedded text has %d chars, below minimum %d", pageNum, len(text), minChars)
		}
		headings := ExtractHeadings(text)
		repaired = append(repaired, repairedPage{pageNum: pageNum, state: state, docID: docID, text: text, headings: headings})
		totalChars += len(text)

		query := fmt.Sprintf(`{
			OcrResult(filter: {_pageID: {_eq: "%s"}}) {
				_docID
			}
		}`, docID)
		resp, err := book.Store.Execute(ctx, query, nil)
		if err != nil {
			return nil, fmt.Errorf("query prior PDF text result for page %d: %w", pageNum, err)
		}
		if errMsg := resp.Error(); errMsg != "" {
			return nil, fmt.Errorf("query prior PDF text result for page %d: %s", pageNum, errMsg)
		}
		if results, ok := resp.Data["OcrResult"].([]any); ok {
			for _, raw := range results {
				result, ok := raw.(map[string]any)
				if !ok {
					continue
				}
				resultID, _ := result["_docID"].(string)
				if resultID != "" {
					deleteOps = append(deleteOps, defra.WriteOp{Collection: "OcrResult", DocID: resultID, Op: defra.OpDelete, Source: "RepairPDFTextPages:delete_prior"})
				}
			}
		}
	}

	ops := make([]defra.WriteOp, 0, len(deleteOps)+2*len(repaired))
	ops = append(ops, deleteOps...)
	for _, page := range repaired {
		headingsJSON, err := json.Marshal(page.headings)
		if err != nil {
			return nil, fmt.Errorf("marshal headings for page %d: %w", page.pageNum, err)
		}
		ops = append(ops,
			defra.WriteOp{
				Collection: "OcrResult",
				Document: map[string]any{
					"_pageID":  page.docID,
					"provider": PDFTextProvider,
					"text":     page.text,
					"provider_metadata": map[string]any{
						"source": "embedded_pdf_text",
					},
				},
				Op:     defra.OpCreate,
				Source: "RepairPDFTextPages:create_result",
			},
			defra.WriteOp{
				Collection: "Page",
				DocID:      page.docID,
				Document: map[string]any{
					"ocr_complete":          true,
					"ocr_markdown":          page.text,
					"headings":              string(headingsJSON),
					"header":                nil,
					"footer":                nil,
					"ocr_quarantined":       false,
					"ocr_quarantine_reason": nil,
				},
				Op:     defra.OpUpdate,
				Source: "RepairPDFTextPages:update_page",
			},
		)
	}
	results, err := book.Store.SendManySync(ctx, ops)
	if err != nil {
		return nil, fmt.Errorf("persist PDF text repair: %w", err)
	}
	for i, result := range results {
		if result.Err != nil {
			return nil, fmt.Errorf("persist PDF text repair operation %d for %s: %w", i, result.DocID, result.Err)
		}
	}

	for _, page := range repaired {
		page.state.ResetOcrProviders(book.OcrProviders)
		page.state.ClearOCRQuarantine()
		page.state.SetOcrMarkdownWithHeadings(page.text, page.headings)
		page.state.SetOCRComplete(true)
	}
	return &PDFTextRepairResult{Pages: pages, Characters: totalChars, DeletedResults: len(deleteOps)}, nil
}

func extractEmbeddedPDFText(ctx context.Context, pdfPath string, pageNum int) (string, error) {
	page := fmt.Sprintf("%d", pageNum)
	cmd := exec.CommandContext(ctx, "pdftotext", "-f", page, "-l", page, "-layout", pdfPath, "-")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return "", fmt.Errorf("pdftotext failed: %w (output: %s)", err, strings.TrimSpace(string(output)))
	}
	// Poppler terminates pages with form feed. It is transport framing, not book text.
	text := strings.TrimSpace(strings.ReplaceAll(string(output), "\f", ""))
	return text, nil
}
