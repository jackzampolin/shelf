package tools

import (
	"context"
	"fmt"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/providers"
)

func writeResultTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "write_result",
			Description: "Submit the final result for this chapter search. Call this when you've found the page where the entry begins, or determined it cannot be found.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"scan_page": map[string]any{
						"anyOf": []map[string]any{
							{"type": "integer", "minimum": 1},
							{"type": "null"},
						},
						"description": "The scan page number where this entry begins, or null if not found",
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

func (t *ChapterFinderTools) writeResult(ctx context.Context, args map[string]any) (string, error) {
	reasoning, _ := args["reasoning"].(string)
	if reasoning == "" {
		reasoning = "No reasoning provided"
	}

	result := &chapter_finder.Result{
		Reasoning: reasoning,
	}

	// Parse scan_page (can be float64 from JSON or nil)
	if scanPageF, ok := args["scan_page"].(float64); ok {
		scanPage := int(scanPageF)
		if scanPage >= 1 && scanPage <= t.book.TotalPages {
			result.ScanPage = &scanPage
		}
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
