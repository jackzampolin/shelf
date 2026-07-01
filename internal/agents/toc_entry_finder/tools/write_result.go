package tools

import (
	"context"
	"encoding/json"
	"fmt"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/providers"
)

func writeResultTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "write_result",
			Description: "Submit the final result for this ToC entry search. Call this when you've found the page where the entry begins, or determined it cannot be found.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"scan_page": map[string]any{
						"type":        "integer",
						"description": "The scan page number where this entry begins. Omit this field entirely if the entry cannot be found.",
					},
					"reasoning": map[string]any{
						"type":        "string",
						"description": "Brief explanation of how you found the page, or why it couldn't be found",
					},
				},
				"required": []string{"reasoning"},
			}),
		},
	}
}

func (t *TocEntryFinderTools) writeResult(ctx context.Context, args map[string]any) (string, error) {
	reasoning, _ := args["reasoning"].(string)
	if reasoning == "" {
		reasoning = "No reasoning provided"
	}

	result := &toc_entry_finder.Result{
		Reasoning: reasoning,
	}

	// Parse scan_page (can be float64 from JSON or nil)
	if scanPageF, ok := args["scan_page"].(float64); ok {
		scanPage := int(scanPageF)
		if scanPage < 1 || scanPage > t.book.TotalPages {
			return jsonError(fmt.Sprintf("write_result rejected scan_page %d: book has pages 1-%d. Use grep_text and get_page_ocr to inspect a valid candidate page.", scanPage, t.book.TotalPages)), nil
		}
		if rejection := t.validateWriteResultEvidence(ctx, scanPage); rejection != "" {
			return rejection, nil
		}
		result.ScanPage = &scanPage
	} else {
		return jsonError("write_result rejected: scan_page is required for ToC linking. Keep searching with grep_text and get_page_ocr; only call write_result after OCR evidence shows the target title or entry number on the candidate page."), nil
	}

	t.pendingResult = result

	// Build result summary
	summary := map[string]any{
		"reasoning": reasoning,
	}
	if result.ScanPage != nil {
		summary["scan_page"] = *result.ScanPage
		summary["message"] = fmt.Sprintf("Entry found on page %d", *result.ScanPage)
	} else {
		summary["scan_page"] = nil
		summary["message"] = "Entry not found"
	}

	return jsonSuccess(summary), nil
}

func (t *TocEntryFinderTools) validateWriteResultEvidence(ctx context.Context, scanPage int) string {
	evidence, rejection, err := t.ValidateCandidatePage(ctx, scanPage)
	if err != nil {
		return jsonWriteResultRejected(scanPage, fmt.Sprintf("could not load OCR for validation: %v", err), nil)
	}
	if rejection == "" {
		return ""
	}
	return jsonWriteResultRejected(scanPage, rejection, evidence)
}

func jsonWriteResultRejected(scanPage int, reason string, evidence any) string {
	result := map[string]any{
		"success":            false,
		"error":              "write_result rejected",
		"rejected_scan_page": scanPage,
		"reason":             reason,
		"next_steps": []string{
			"Call grep_text with the title-only query and inspect the dense cluster nearest the expected scan range.",
			"Call get_page_ocr on the first page of that cluster before trying write_result again.",
			"Only call write_result for a page with a matching section header, a distinctive title-prefix section header, matching entry-number section header, the first page of a title page-header cluster, or the first available scanned page after a missing expected printed page.",
		},
	}
	if evidence != nil {
		result["evidence"] = evidence
	}
	b, _ := json.MarshalIndent(result, "", "  ")
	return string(b)
}
