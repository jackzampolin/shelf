package endpoints

import (
	"context"
	"encoding/json"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// buildMetadataStatus queries the Book record and fills the metadata section
// plus the other book-level fields the record carries: total pages, structure
// flags and phase counters, and the finalize/pattern-analysis ToC sub-phase
// state (PatternComplete, DiscoverComplete, ValidateComplete).
func buildMetadataStatus(ctx context.Context, client *defra.Client, bookID string, resp *DetailedJobStatusResponse) error {
	// Query book info
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
			title
			subtitle
			author
			isbn
			lccn
			publisher
			publication_year
			language
			description
			cover_page
			metadata_started
			metadata_complete
			metadata_failed
			structure_started
			structure_complete
			structure_failed
			pattern_analysis_json
			structure_retries
			structure_phase
			structure_chapters_total
			structure_chapters_extracted
			structure_chapters_polished
			structure_polish_failed
			finalize_entries_total
			finalize_entries_complete
			finalize_entries_found
			finalize_gaps_total
			finalize_gaps_complete
			finalize_gaps_fixes
		}
	}`, bookID)

	bookResp, err := client.Execute(ctx, bookQuery, nil)
	if err != nil {
		return fmt.Errorf("failed to query book: %w", err)
	}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				resp.TotalPages = int(pc)
			}

			// Metadata status
			if v, ok := book["metadata_started"].(bool); ok {
				resp.Metadata.Started = v
			}
			if v, ok := book["metadata_complete"].(bool); ok {
				resp.Metadata.Complete = v
			}
			if v, ok := book["metadata_failed"].(bool); ok {
				resp.Metadata.Failed = v
			}

			// Note: The old pattern_analysis stage was removed from the pipeline.
			// Pattern analysis now happens as part of finalize_toc and is tracked via
			// resp.ToC.PatternComplete (set from pattern_analysis_json existence).

			// If metadata is complete, include the data
			if resp.Metadata.Complete {
				resp.Metadata.Data = &BookMetadata{}
				if v, ok := book["title"].(string); ok {
					resp.Metadata.Data.Title = v
				}
				if v, ok := book["subtitle"].(string); ok {
					resp.Metadata.Data.Subtitle = v
				}
				if v, ok := book["author"].(string); ok {
					resp.Metadata.Data.Author = v
				}
				if v, ok := book["isbn"].(string); ok {
					resp.Metadata.Data.ISBN = v
				}
				if v, ok := book["lccn"].(string); ok {
					resp.Metadata.Data.LCCN = v
				}
				if v, ok := book["publisher"].(string); ok {
					resp.Metadata.Data.Publisher = v
				}
				if v, ok := book["publication_year"].(float64); ok {
					resp.Metadata.Data.PublicationYear = int(v)
				}
				if v, ok := book["language"].(string); ok {
					resp.Metadata.Data.Language = v
				}
				if v, ok := book["description"].(string); ok {
					resp.Metadata.Data.Description = v
				}
				if v, ok := book["cover_page"].(float64); ok {
					resp.Metadata.Data.CoverPage = int(v)
				}
			}

			// Structure status
			if v, ok := book["structure_started"].(bool); ok {
				resp.Structure.Started = v
			}
			if v, ok := book["structure_complete"].(bool); ok {
				resp.Structure.Complete = v
			}
			if v, ok := book["structure_failed"].(bool); ok {
				resp.Structure.Failed = v
			}
			if v, ok := book["structure_retries"].(float64); ok {
				resp.Structure.Retries = int(v)
			}
			// Structure phase tracking
			if v, ok := book["structure_phase"].(string); ok {
				resp.Structure.Phase = v
			}
			if v, ok := book["structure_chapters_total"].(float64); ok {
				resp.Structure.ChaptersTotal = int(v)
			}
			if v, ok := book["structure_chapters_extracted"].(float64); ok {
				resp.Structure.ChaptersExtracted = int(v)
			}
			if v, ok := book["structure_chapters_polished"].(float64); ok {
				resp.Structure.ChaptersPolished = int(v)
			}
			if v, ok := book["structure_polish_failed"].(float64); ok {
				resp.Structure.PolishFailed = int(v)
			}

			// Finalize progress tracking
			var finalizeEntriesTotal, finalizeEntriesComplete, finalizeEntriesFound int
			var finalizeGapsTotal, finalizeGapsComplete, finalizeGapsFixes int
			if v, ok := book["finalize_entries_total"].(float64); ok {
				finalizeEntriesTotal = int(v)
			}
			if v, ok := book["finalize_entries_complete"].(float64); ok {
				finalizeEntriesComplete = int(v)
			}
			if v, ok := book["finalize_entries_found"].(float64); ok {
				finalizeEntriesFound = int(v)
			}
			if v, ok := book["finalize_gaps_total"].(float64); ok {
				finalizeGapsTotal = int(v)
			}
			if v, ok := book["finalize_gaps_complete"].(float64); ok {
				finalizeGapsComplete = int(v)
			}
			if v, ok := book["finalize_gaps_fixes"].(float64); ok {
				finalizeGapsFixes = int(v)
			}
			_ = finalizeEntriesFound // Tracked in DB, completion uses finalizeEntriesTotal
			_ = finalizeGapsFixes    // Used for future gap fix tracking

			// Parse pattern_analysis_json for finalize_toc sub-phase tracking details
			// Pattern complete is determined by existence of pattern_analysis_json (from finalize_toc)
			if patternJSON, ok := book["pattern_analysis_json"].(string); ok && patternJSON != "" {
				resp.ToC.PatternComplete = true
				var patternData struct {
					Reasoning string `json:"reasoning"`
					Patterns  []struct {
						PatternType   string `json:"pattern_type"`
						LevelName     string `json:"level_name"`
						HeadingFormat string `json:"heading_format"`
						RangeStart    string `json:"range_start"`
						RangeEnd      string `json:"range_end"`
						Level         int    `json:"level"`
						Reasoning     string `json:"reasoning"`
					} `json:"patterns"`
					ExcludedRanges []struct {
						StartPage int    `json:"start_page"`
						EndPage   int    `json:"end_page"`
						Reason    string `json:"reason"`
					} `json:"excluded_ranges"`
					EntriesToFind []struct{} `json:"entries_to_find"`
				}
				if err := json.Unmarshal([]byte(patternJSON), &patternData); err == nil {
					resp.ToC.PatternsFound = len(patternData.Patterns)
					resp.ToC.ExcludedRanges = len(patternData.ExcludedRanges)
					resp.ToC.EntriesToFind = len(patternData.EntriesToFind)

					// Include full pattern analysis result
					result := &PatternAnalysisResult{
						Reasoning: patternData.Reasoning,
					}
					for _, p := range patternData.Patterns {
						result.Patterns = append(result.Patterns, DiscoveredPattern{
							PatternType:   p.PatternType,
							LevelName:     p.LevelName,
							HeadingFormat: p.HeadingFormat,
							RangeStart:    p.RangeStart,
							RangeEnd:      p.RangeEnd,
							Level:         p.Level,
							Reasoning:     p.Reasoning,
						})
					}
					for _, e := range patternData.ExcludedRanges {
						result.ExcludedRanges = append(result.ExcludedRanges, ExcludedRange{
							StartPage: e.StartPage,
							EndPage:   e.EndPage,
							Reason:    e.Reason,
						})
					}
					resp.ToC.PatternAnalysis = result
				}
			}

			// Set DiscoverComplete and ValidateComplete based on finalize progress
			// DiscoverComplete: pattern analysis done AND all entries discovered (complete >= total)
			if resp.ToC.PatternComplete {
				if finalizeEntriesTotal == 0 {
					// No entries to find - discover phase is trivially complete
					resp.ToC.DiscoverComplete = true
				} else if finalizeEntriesComplete >= finalizeEntriesTotal {
					// All entries have been processed
					resp.ToC.DiscoverComplete = true
				}
			}

			// ValidateComplete: discover is complete AND all gaps processed (complete >= total)
			if resp.ToC.DiscoverComplete {
				if resp.ToC.FinalizeComplete {
					// Overall finalize done means validation is done
					resp.ToC.ValidateComplete = true
				} else if finalizeGapsTotal == 0 {
					// No gaps to validate - trivially complete
					resp.ToC.ValidateComplete = true
				} else if finalizeGapsComplete >= finalizeGapsTotal {
					// All gaps have been processed
					resp.ToC.ValidateComplete = true
				}
			}
		}
	}

	return nil
}

// buildOcrProgress fills OCR stage totals, page completion counts, and
// per-provider OCR progress from metrics. It relies on resp.TotalPages set by
// buildMetadataStatus.
func buildOcrProgress(ctx context.Context, client *defra.Client, bookID string, resp *DetailedJobStatusResponse) error {
	// Set totals for stages
	resp.Stages.OCR.Total = resp.TotalPages

	// Query pages for completion counts
	pageQuery := fmt.Sprintf(`{
		Page(filter: {_bookID: {_eq: "%s"}}) {
			ocr_complete
			ocr_quarantined
		}
	}`, bookID)

	pageResp, err := client.Execute(ctx, pageQuery, nil)
	if err != nil {
		return fmt.Errorf("failed to query pages: %w", err)
	}

	if pages, ok := pageResp.Data["Page"].([]any); ok {
		for _, p := range pages {
			page, ok := p.(map[string]any)
			if !ok {
				continue
			}
			if ocrComplete, ok := page["ocr_complete"].(bool); ok && ocrComplete {
				resp.Stages.OCR.Complete++
			} else if quarantined, ok := page["ocr_quarantined"].(bool); ok && quarantined {
				resp.Stages.OCR.Quarantined++
			}
		}
	}

	// Populate per-provider OCR progress from metrics (OcrResult collection
	// is no longer used after Mistral-only consolidation)
	metricsQueryForProgress := svcctx.MetricsQueryFrom(ctx)
	if metricsQueryForProgress != nil {
		ocrMetrics, err := metricsQueryForProgress.List(ctx, metrics.Filter{BookID: bookID, Stage: "ocr"}, 0)
		if err == nil {
			providerCounts := make(map[string]int)
			for _, m := range ocrMetrics {
				if m.Success {
					providerCounts[m.Provider]++
				}
			}
			for provider, count := range providerCounts {
				resp.OcrProgress[provider] = ProviderProgress{
					Complete: count,
					Total:    resp.TotalPages,
				}
			}
		}
	}

	return nil
}
