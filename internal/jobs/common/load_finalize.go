package common

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// LoadFinalizeState loads finalize phase state from DefraDB.
// This includes the finalize phase from ToC and pattern analysis results from Book.
func LoadFinalizeState(ctx context.Context, book *BookState, tocDocID string) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	// Validate IDs to prevent GraphQL injection
	if err := defra.ValidateID(book.BookID); err != nil {
		return fmt.Errorf("invalid book ID: %w", err)
	}
	if tocDocID != "" {
		if err := defra.ValidateID(tocDocID); err != nil {
			return fmt.Errorf("invalid ToC doc ID: %w", err)
		}
	}

	logger := svcctx.LoggerFrom(ctx)

	// Load finalize phase from ToC
	if tocDocID != "" {
		tocQuery := fmt.Sprintf(`{
			ToC(filter: {_docID: {_eq: "%s"}}) {
				finalize_phase
			}
		}`, tocDocID)

		tocResp, err := defraClient.Execute(ctx, tocQuery, nil)
		if err != nil {
			return fmt.Errorf("failed to query ToC for finalize phase: %w", err)
		}

		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if tocData, ok := tocs[0].(map[string]any); ok {
				if phase, ok := tocData["finalize_phase"].(string); ok && phase != "" {
					book.SetFinalizePhase(phase)
				}
			}
		}
	}

	// Load pattern analysis results and progress from Book
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			pattern_analysis_json
			finalize_entries_total
			finalize_entries_complete
			finalize_entries_found
			finalize_gaps_total
			finalize_gaps_complete
			finalize_gaps_fixes
			toc_link_entries_total
			toc_link_entries_done
		}
	}`, book.BookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return fmt.Errorf("failed to query Book for finalize state: %w", err)
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if bookData, ok := books[0].(map[string]any); ok {
			// Load pattern analysis JSON
			if paJSON, ok := bookData["pattern_analysis_json"].(string); ok && paJSON != "" {
				var data struct {
					Patterns      []DiscoveredPattern `json:"patterns"`
					Excluded      []ExcludedRange     `json:"excluded_ranges"`
					EntriesToFind []*EntryToFind      `json:"entries_to_find"`
					Reasoning     string              `json:"reasoning"`
				}
				if err := json.Unmarshal([]byte(paJSON), &data); err == nil {
					book.SetFinalizePatternResult(&FinalizePatternResult{
						Patterns:  data.Patterns,
						Excluded:  data.Excluded,
						Reasoning: data.Reasoning,
					})
					book.SetEntriesToFind(data.EntriesToFind)
				} else if logger != nil {
					logger.Warn("failed to unmarshal pattern_analysis_json", "error", err)
				}
			}

			// Load progress counters
			if et, ok := bookData["finalize_entries_total"].(float64); ok {
				book.SetFinalizeEntriesTotal(int(et))
			}
			var entriesComplete, entriesFound, gapsComplete, gapsFixes int
			if ec, ok := bookData["finalize_entries_complete"].(float64); ok {
				entriesComplete = int(ec)
			}
			if ef, ok := bookData["finalize_entries_found"].(float64); ok {
				entriesFound = int(ef)
			}
			if gt, ok := bookData["finalize_gaps_total"].(float64); ok {
				book.SetFinalizeGapsTotal(int(gt))
			}
			if gc, ok := bookData["finalize_gaps_complete"].(float64); ok {
				gapsComplete = int(gc)
			}
			if gf, ok := bookData["finalize_gaps_fixes"].(float64); ok {
				gapsFixes = int(gf)
			}
			book.SetFinalizeProgress(entriesComplete, entriesFound, gapsComplete, gapsFixes)

			// Load toc link progress counters
			var tocLinkTotal, tocLinkDone int
			if t, ok := bookData["toc_link_entries_total"].(float64); ok {
				tocLinkTotal = int(t)
			}
			if d, ok := bookData["toc_link_entries_done"].(float64); ok {
				tocLinkDone = int(d)
			}
			if tocLinkTotal > 0 || tocLinkDone > 0 {
				book.SetTocLinkProgress(tocLinkTotal, tocLinkDone)
			}
		}
	}

	if logger != nil {
		logger.Debug("loaded finalize state",
			"book_id", book.BookID,
			"phase", book.GetFinalizePhase(),
			"has_pattern_result", book.GetFinalizePatternResult() != nil)
	}

	return nil
}
