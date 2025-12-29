package tools

import (
	"context"
	"fmt"

	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/providers"
)

func writeTocResultTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "write_toc_result",
			Description: "Write final ToC search result and complete the task. IMPORTANT: If toc_found=false, set toc_page_range to null (not a dummy range). Your page observations will be automatically compiled into structure_notes. If ToC found, provide structure_summary with global hierarchy analysis.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"toc_found": map[string]any{
						"type":        "boolean",
						"description": "Whether ToC was found",
					},
					"toc_page_range": map[string]any{
						"anyOf": []map[string]any{
							{
								"type": "object",
								"properties": map[string]any{
									"start_page": map[string]any{"type": "integer", "minimum": 1},
									"end_page":   map[string]any{"type": "integer", "minimum": 1},
								},
								"required": []string{"start_page", "end_page"},
							},
							{"type": "null"},
						},
						"description": "ToC page range with start_page and end_page (both >= 1), or null if ToC not found",
					},
					"confidence": map[string]any{
						"type":        "number",
						"description": "Confidence score 0.0-1.0",
						"minimum":     0.0,
						"maximum":     1.0,
					},
					"search_strategy_used": map[string]any{
						"type":        "string",
						"description": "Strategy used: grep_report, grep_with_scan, or not_found",
					},
					"reasoning": map[string]any{
						"type":        "string",
						"description": "1-2 sentence explanation of grep hints + what you saw in images",
					},
					"structure_summary": map[string]any{
						"type":        "object",
						"description": "Global structure analysis (REQUIRED if toc_found=true, null otherwise)",
						"properties": map[string]any{
							"total_levels": map[string]any{
								"type":        "integer",
								"description": "Total hierarchy levels (1, 2, or 3)",
								"minimum":     1,
								"maximum":     3,
							},
							"level_patterns": map[string]any{
								"type":        "object",
								"description": "Visual/structural patterns for each level (keys: '1', '2', '3')",
							},
							"consistency_notes": map[string]any{
								"type":        "array",
								"description": "Notes about structural consistency or variations",
								"items":       map[string]any{"type": "string"},
							},
						},
						"required": []string{"total_levels", "level_patterns"},
					},
				},
				"required": []string{"toc_found", "confidence", "search_strategy_used", "reasoning"},
			}),
		},
	}
}

func (t *ToCFinderTools) writeTocResult(ctx context.Context, args map[string]any) (string, error) {
	tocFound, _ := args["toc_found"].(bool)
	confidence, _ := args["confidence"].(float64)
	searchStrategy, _ := args["search_strategy_used"].(string)
	reasoning, _ := args["reasoning"].(string)

	// Build result
	result := &toc_finder.Result{
		ToCFound:           tocFound,
		Confidence:         confidence,
		SearchStrategyUsed: searchStrategy,
		Reasoning:          reasoning,
		PagesChecked:       len(t.pageObservations),
	}

	// Parse page range if provided
	if tocPageRange, ok := args["toc_page_range"].(map[string]any); ok && tocFound {
		startPage := int(tocPageRange["start_page"].(float64))
		endPage := int(tocPageRange["end_page"].(float64))
		result.ToCPageRange = &toc_finder.PageRange{
			StartPage: startPage,
			EndPage:   endPage,
		}
	}

	// Compile structure notes from observations
	if tocFound && len(t.pageObservations) > 0 {
		result.StructureNotes = make(map[int]string)
		for _, obs := range t.pageObservations {
			result.StructureNotes[obs.PageNum] = obs.Observations
		}
	}

	// Parse structure summary if provided
	if structureSummaryRaw, ok := args["structure_summary"].(map[string]any); ok && tocFound {
		totalLevels := int(structureSummaryRaw["total_levels"].(float64))
		result.StructureSummary = &toc_finder.StructureSummary{
			TotalLevels:   totalLevels,
			LevelPatterns: make(map[string]toc_finder.LevelPattern),
		}

		if levelPatterns, ok := structureSummaryRaw["level_patterns"].(map[string]any); ok {
			for levelKey, patternRaw := range levelPatterns {
				pattern, ok := patternRaw.(map[string]any)
				if !ok {
					continue
				}

				lp := toc_finder.LevelPattern{
					HasPageNumbers: pattern["has_page_numbers"].(bool),
				}
				if visual, ok := pattern["visual"].(string); ok {
					lp.Visual = visual
				}
				if numbering, ok := pattern["numbering"].(string); ok {
					lp.Numbering = &numbering
				}
				if semanticType, ok := pattern["semantic_type"].(string); ok {
					lp.SemanticType = &semanticType
				}

				result.StructureSummary.LevelPatterns[levelKey] = lp
			}
		}

		if consistencyNotes, ok := structureSummaryRaw["consistency_notes"].([]any); ok {
			for _, note := range consistencyNotes {
				if noteStr, ok := note.(string); ok {
					result.StructureSummary.ConsistencyNotes = append(result.StructureSummary.ConsistencyNotes, noteStr)
				}
			}
		}
	}

	t.pendingResult = result

	resultSummary := map[string]any{
		"toc_found":  tocFound,
		"confidence": confidence,
	}
	if result.ToCPageRange != nil {
		resultSummary["toc_page_range"] = fmt.Sprintf("%d-%d", result.ToCPageRange.StartPage, result.ToCPageRange.EndPage)
	}
	if result.StructureNotes != nil {
		resultSummary["structure_notes_compiled"] = fmt.Sprintf("from %d page observations", len(t.pageObservations))
	}
	if result.StructureSummary != nil {
		resultSummary["structure_summary_compiled"] = fmt.Sprintf("%d levels analyzed", result.StructureSummary.TotalLevels)
	}

	return jsonSuccess(map[string]any{
		"message": "ToC search complete",
		"result":  resultSummary,
	}), nil
}
