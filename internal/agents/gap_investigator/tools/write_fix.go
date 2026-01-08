package tools

import (
	"context"
	"fmt"

	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/providers"
)

func writeFixTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "write_fix",
			Description: "Submit your fix recommendation for this gap. Call this when you've determined the cause and the appropriate fix.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"fix_type": map[string]any{
						"type":        "string",
						"enum":        []string{"add_entry", "correct_entry", "no_fix_needed", "flag_for_review"},
						"description": "Type of fix: add_entry (new entry needed), correct_entry (fix existing), no_fix_needed (gap is intentional), flag_for_review (unsure)",
					},
					"scan_page": map[string]any{
						"type":        "integer",
						"description": "For add_entry: the page where the new entry starts",
					},
					"title": map[string]any{
						"type":        "string",
						"description": "For add_entry: the title of the new entry",
					},
					"level": map[string]any{
						"type":        "integer",
						"description": "For add_entry: structural level (1=part, 2=chapter, 3=section)",
					},
					"level_name": map[string]any{
						"type":        "string",
						"description": "For add_entry: level name (chapter, part, section, etc.)",
					},
					"entry_doc_id": map[string]any{
						"type":        "string",
						"description": "For correct_entry: the document ID of the entry to correct",
					},
					"new_scan_page": map[string]any{
						"type":        "integer",
						"description": "For correct_entry: the corrected scan page",
					},
					"reasoning": map[string]any{
						"type":        "string",
						"description": "Explanation of your investigation and why this fix is appropriate",
					},
				},
				"required": []string{"fix_type", "reasoning"},
			}),
		},
	}
}

func (t *GapInvestigatorTools) writeFix(ctx context.Context, args map[string]any) (string, error) {
	fixType, _ := args["fix_type"].(string)
	reasoning, _ := args["reasoning"].(string)

	if fixType == "" {
		return jsonError("fix_type is required"), nil
	}
	if reasoning == "" {
		reasoning = "No reasoning provided"
	}

	result := &gap_investigator.Result{
		FixType:   fixType,
		Reasoning: reasoning,
	}

	switch fixType {
	case "add_entry":
		if scanPage, ok := args["scan_page"].(float64); ok {
			result.ScanPage = int(scanPage)
		} else {
			return jsonError("scan_page is required for add_entry"), nil
		}
		if title, ok := args["title"].(string); ok {
			result.Title = title
		}
		if level, ok := args["level"].(float64); ok {
			result.Level = int(level)
		}
		if levelName, ok := args["level_name"].(string); ok {
			result.LevelName = levelName
		}

	case "correct_entry":
		if entryDocID, ok := args["entry_doc_id"].(string); ok {
			result.EntryDocID = entryDocID
		} else {
			return jsonError("entry_doc_id is required for correct_entry"), nil
		}
		if newScanPage, ok := args["new_scan_page"].(float64); ok {
			result.ScanPage = int(newScanPage)
		}

	case "flag_for_review":
		result.Flagged = true

	case "no_fix_needed":
		// Nothing extra needed
	}

	t.pendingResult = result

	// Build result summary
	summary := map[string]any{
		"fix_type":  fixType,
		"reasoning": reasoning,
	}

	switch fixType {
	case "add_entry":
		summary["message"] = fmt.Sprintf("Recommending add_entry: %q at page %d", result.Title, result.ScanPage)
	case "correct_entry":
		summary["message"] = fmt.Sprintf("Recommending correct_entry: %s to page %d", result.EntryDocID, result.ScanPage)
	case "no_fix_needed":
		summary["message"] = "Gap is intentional - no fix needed"
	case "flag_for_review":
		summary["message"] = "Flagged for manual review"
	}

	return jsonSuccess(summary), nil
}
