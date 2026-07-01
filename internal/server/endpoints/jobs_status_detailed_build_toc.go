package endpoints

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// buildTocStatus queries the Book->ToC relationship and fills the ToC stage
// flags and entries (finder/extract/link/finalize state, entry list, link
// counts). Query errors are ignored so a missing ToC leaves the zero values.
func buildTocStatus(ctx context.Context, client *defra.Client, bookID string, resp *DetailedJobStatusResponse) error {
	// Query ToC status via the Book->ToC relationship
	// ToC doesn't have book_id field, it's linked via Book.toc_id
	tocQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			toc {
				finder_started
				finder_complete
				finder_failed
				toc_found
				start_page
				end_page
				extract_started
				extract_complete
				extract_failed
				link_started
				link_complete
				link_failed
				link_retries
				finalize_started
				finalize_complete
				finalize_failed
				finalize_retries
				entries {
					entry_number
					title
					level
					level_name
					printed_page_number
					sort_order
					source
					actual_page {
						page_num
					}
				}
			}
		}
	}`, bookID)

	tocResp, err := client.Execute(ctx, tocQuery, nil)
	if err == nil {
		// Parse Book -> toc relationship
		if books, ok := tocResp.Data["Book"].([]any); ok && len(books) > 0 {
			if book, ok := books[0].(map[string]any); ok {
				if toc, ok := book["toc"].(map[string]any); ok {
					if v, ok := toc["finder_started"].(bool); ok {
						resp.ToC.FinderStarted = v
					}
					if v, ok := toc["finder_complete"].(bool); ok {
						resp.ToC.FinderComplete = v
					}
					if v, ok := toc["finder_failed"].(bool); ok {
						resp.ToC.FinderFailed = v
					}
					if v, ok := toc["toc_found"].(bool); ok {
						resp.ToC.Found = v
					}
					if v, ok := toc["start_page"].(float64); ok {
						resp.ToC.StartPage = int(v)
					}
					if v, ok := toc["end_page"].(float64); ok {
						resp.ToC.EndPage = int(v)
					}
					if v, ok := toc["extract_started"].(bool); ok {
						resp.ToC.ExtractStarted = v
					}
					if v, ok := toc["extract_complete"].(bool); ok {
						resp.ToC.ExtractComplete = v
					}
					if v, ok := toc["extract_failed"].(bool); ok {
						resp.ToC.ExtractFailed = v
					}
					if v, ok := toc["link_started"].(bool); ok {
						resp.ToC.LinkStarted = v
					}
					if v, ok := toc["link_complete"].(bool); ok {
						resp.ToC.LinkComplete = v
					}
					if v, ok := toc["link_failed"].(bool); ok {
						resp.ToC.LinkFailed = v
					}
					if v, ok := toc["link_retries"].(float64); ok {
						resp.ToC.LinkRetries = int(v)
					}
					if v, ok := toc["finalize_started"].(bool); ok {
						resp.ToC.FinalizeStarted = v
					}
					if v, ok := toc["finalize_complete"].(bool); ok {
						resp.ToC.FinalizeComplete = v
					}
					if v, ok := toc["finalize_failed"].(bool); ok {
						resp.ToC.FinalizeFailed = v
					}
					if v, ok := toc["finalize_retries"].(float64); ok {
						resp.ToC.FinalizeRetries = int(v)
					}

					// Parse ToC entries
					if entries, ok := toc["entries"].([]any); ok {
						resp.ToC.EntryCount = len(entries)
						for _, e := range entries {
							if entry, ok := e.(map[string]any); ok {
								tocEntry := ToCEntry{}
								if v, ok := entry["entry_number"].(string); ok {
									tocEntry.EntryNumber = v
								}
								if v, ok := entry["title"].(string); ok {
									tocEntry.Title = v
								}
								if v, ok := entry["level"].(float64); ok {
									tocEntry.Level = int(v)
								}
								if v, ok := entry["level_name"].(string); ok {
									tocEntry.LevelName = v
								}
								if v, ok := entry["printed_page_number"].(string); ok {
									tocEntry.PrintedPageNumber = v
								}
								if v, ok := entry["sort_order"].(float64); ok {
									tocEntry.SortOrder = int(v)
								}
								if v, ok := entry["source"].(string); ok {
									tocEntry.Source = v
									if v == "discovered" {
										resp.ToC.EntriesDiscovered++
									}
								}
								// Check if entry is linked to actual page
								if actualPage, ok := entry["actual_page"].(map[string]any); ok {
									if pageNum, ok := actualPage["page_num"].(float64); ok {
										tocEntry.ActualPageNum = int(pageNum)
										tocEntry.IsLinked = true
										resp.ToC.EntriesLinked++
									}
								}
								resp.ToC.Entries = append(resp.ToC.Entries, tocEntry)
							}
						}
						// Sort entries by sort_order since DefraDB doesn't guarantee order
						sort.Slice(resp.ToC.Entries, func(i, j int) bool {
							return resp.ToC.Entries[i].SortOrder < resp.ToC.Entries[j].SortOrder
						})
					}
				}
			}
		}
	}

	// DiscoverComplete and ValidateComplete are now set inside the book parsing block
	// where we have access to finalize progress tracking fields

	return nil
}

// buildStructureStatus fills the chapter count for the structure section once
// the structure stage is complete. The remaining structure fields come from
// the Book record via buildMetadataStatus.
func buildStructureStatus(ctx context.Context, client *defra.Client, bookID string, resp *DetailedJobStatusResponse) error {
	// Query chapter count for structure status
	if resp.Structure.Complete {
		chapterQuery := fmt.Sprintf(`{
			Chapter(filter: {book: {_docID: {_eq: %q}}}) {
				_docID
			}
		}`, bookID)
		if chapterResp, err := client.Execute(ctx, chapterQuery, nil); err == nil {
			if chapters, ok := chapterResp.Data["Chapter"].([]any); ok {
				resp.Structure.ChapterCount = len(chapters)
			}
		}
	}

	return nil
}

// buildCostBreakdown fills the per-stage and per-provider cost fields from the
// metrics stage breakdown. Metrics errors are logged, not returned, so cost
// gaps never fail the status call.
func buildCostBreakdown(ctx context.Context, bookID string, resp *DetailedJobStatusResponse) error {
	// Query costs from metrics using stage-based breakdown
	metricsQuery := svcctx.MetricsQueryFrom(ctx)
	if metricsQuery != nil {
		costByStage, err := metricsQuery.BookStageBreakdown(ctx, bookID)
		if err != nil {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Warn("failed to query cost breakdown", "book_id", bookID, "error", err)
			}
		} else {
			// OCR total cost from stage breakdown
			if ocrCost, ok := costByStage["ocr"]; ok {
				resp.Stages.OCR.TotalCostUSD = ocrCost
			}
			// Per-provider OCR cost via separate query
			if len(resp.OcrProgress) > 0 {
				ocrByProvider, err := metricsQuery.CostByProvider(ctx, metrics.Filter{BookID: bookID, Stage: "ocr"})
				if err == nil {
					for provider, cost := range ocrByProvider {
						resp.Stages.OCR.CostByProvider[provider] = cost
						if prog, ok := resp.OcrProgress[provider]; ok {
							prog.CostUSD = cost
							resp.OcrProgress[provider] = prog
						}
					}
				}
			}

			// Pattern Analysis cost
			if cost, ok := costByStage["toc-pattern"]; ok {
				resp.Stages.PatternAnalysis.CostUSD = cost
			}

			// Metadata cost
			if cost, ok := costByStage["metadata"]; ok {
				resp.Metadata.CostUSD = cost
			}

			// ToC costs (finder + link + discover + validate)
			for _, stage := range []string{"toc", "toc-link", "toc-discover", "toc-validate"} {
				if cost, ok := costByStage[stage]; ok {
					resp.ToC.CostUSD += cost
				}
			}

			// Structure cost (classify + polish)
			for _, stage := range []string{"structure-classify", "structure-polish"} {
				if cost, ok := costByStage[stage]; ok {
					resp.Structure.CostUSD += cost
				}
			}
		}
	}

	return nil
}

// loadAgentLogs fills the recent agent-log summaries, capped at agentLogLimit
// records (0 disables logs). Query errors are ignored.
func loadAgentLogs(ctx context.Context, client *defra.Client, bookID string, resp *DetailedJobStatusResponse, agentLogLimit int) error {
	// Query recent agent logs. Use a default limit because books with repeated
	// agent retries can otherwise return thousands of records in one status call.
	if agentLogLimit > 0 {
		agentQuery := fmt.Sprintf(`{
			AgentRun(filter: {book_id: {_eq: "%s"}}, order: {started_at: DESC}, limit: %d) {
				_docID
				agent_type
				started_at
				completed_at
				iterations
				success
				error
			}
		}`, bookID, agentLogLimit)

		agentResp, err := client.Execute(ctx, agentQuery, nil)
		if err == nil {
			if runs, ok := agentResp.Data["AgentRun"].([]any); ok {
				for _, r := range runs {
					if run, ok := r.(map[string]any); ok {
						log := AgentLogSummary{}
						if v, ok := run["_docID"].(string); ok {
							log.ID = v
						}
						if v, ok := run["agent_type"].(string); ok {
							log.AgentType = v
						}
						if v, ok := run["started_at"].(string); ok {
							log.StartedAt = v
						}
						if v, ok := run["completed_at"].(string); ok {
							log.CompletedAt = v
						}
						if v, ok := run["iterations"].(float64); ok {
							log.Iterations = int(v)
						}
						if v, ok := run["success"].(bool); ok {
							log.Success = v
						}
						if v, ok := run["error"].(string); ok {
							log.Error = v
						}
						resp.AgentLogs = append(resp.AgentLogs, log)
					}
				}
			}
		}
	}

	return nil
}
