package tools

import (
	"context"

	"github.com/jackzampolin/shelf/internal/providers"
)

func getGapContextTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "get_gap_context",
			Description: "Get context about the gap: surrounding entries, body range, and hints about what might be missing. Call this first to understand the situation.",
			Parameters: mustMarshal(map[string]any{
				"type":       "object",
				"properties": map[string]any{},
				"required":   []string{},
			}),
		},
	}
}

func (t *GapInvestigatorTools) getGapContext(ctx context.Context) (string, error) {
	// Build context from gap info
	gapInfo := map[string]any{
		"gap_start":   t.gap.StartPage,
		"gap_end":     t.gap.EndPage,
		"gap_size":    t.gap.Size,
		"body_start":  t.bodyStart,
		"body_end":    t.bodyEnd,
		"total_pages": t.totalPages,
	}

	if t.gap.PrevEntryTitle != "" {
		gapInfo["entry_before"] = map[string]any{
			"title": t.gap.PrevEntryTitle,
			"page":  t.gap.PrevEntryPage,
		}
	}

	if t.gap.NextEntryTitle != "" {
		gapInfo["entry_after"] = map[string]any{
			"title": t.gap.NextEntryTitle,
			"page":  t.gap.NextEntryPage,
		}
	}

	// Add nearby entries for context
	nearbyEntries := []map[string]any{}
	for _, entry := range t.linkedEntries {
		// Include entries within 20 pages of the gap
		if entry.ActualPage >= t.gap.StartPage-20 && entry.ActualPage <= t.gap.EndPage+20 {
			nearbyEntries = append(nearbyEntries, map[string]any{
				"doc_id":     entry.DocID,
				"title":      entry.Title,
				"level":      entry.Level,
				"level_name": entry.LevelName,
				"page":       entry.ActualPage,
			})
		}
	}
	gapInfo["nearby_entries"] = nearbyEntries

	// Add hints based on pattern
	hints := []string{}
	if t.gap.PrevEntryTitle != "" && t.gap.NextEntryTitle != "" {
		hints = append(hints, "Check if there's a missing entry between the surrounding chapters")
	}
	if t.gap.Size > 50 {
		hints = append(hints, "Large gap - might contain multiple missing entries or be back matter")
	}
	if t.gap.Size < 10 {
		hints = append(hints, "Small gap - might just be transition pages or normal chapter length variation")
	}
	gapInfo["investigation_hints"] = hints

	return jsonSuccess(gapInfo), nil
}
