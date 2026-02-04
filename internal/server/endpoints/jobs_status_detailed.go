package endpoints

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"sort"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// DetailedJobStatusResponse is a comprehensive status response with per-provider data.
type DetailedJobStatusResponse struct {
	BookID     string `json:"book_id"`
	TotalPages int    `json:"total_pages"`

	// Per-provider OCR progress
	OcrProgress map[string]ProviderProgress `json:"ocr_progress"`

	// Stage progress with costs
	Stages StageProgress `json:"stages"`

	// Metadata status
	Metadata MetadataStatus `json:"metadata"`

	// ToC status
	ToC ToCStatus `json:"toc"`

	// Structure status (common-structure job)
	Structure StructureStatus `json:"structure"`

	// Agent logs summary
	AgentLogs []AgentLogSummary `json:"agent_logs,omitempty"`
}

// ProviderProgress tracks completion for a single provider.
type ProviderProgress struct {
	Complete int     `json:"complete"`
	Total    int     `json:"total"`
	CostUSD  float64 `json:"cost_usd"`
}

// StageProgress tracks progress and cost for each stage.
type StageProgress struct {
	OCR struct {
		Complete       int                `json:"complete"`
		Total          int                `json:"total"`
		CostByProvider map[string]float64 `json:"cost_by_provider"`
		TotalCostUSD   float64            `json:"total_cost_usd"`
	} `json:"ocr"`
	PatternAnalysis struct {
		Complete bool    `json:"complete"`
		CostUSD  float64 `json:"cost_usd"`
	} `json:"pattern_analysis"`
}

// MetadataStatus represents metadata extraction status.
type MetadataStatus struct {
	Started  bool          `json:"started"`
	Complete bool          `json:"complete"`
	Failed   bool          `json:"failed"`
	CostUSD  float64       `json:"cost_usd"`
	Data     *BookMetadata `json:"data,omitempty"`
}

// BookMetadata contains extracted book metadata.
type BookMetadata struct {
	Title           string   `json:"title,omitempty"`
	Subtitle        string   `json:"subtitle,omitempty"`
	Author          string   `json:"author,omitempty"`
	Authors         []string `json:"authors,omitempty"`
	ISBN            string   `json:"isbn,omitempty"`
	LCCN            string   `json:"lccn,omitempty"`
	Publisher       string   `json:"publisher,omitempty"`
	PublicationYear int      `json:"publication_year,omitempty"`
	Language        string   `json:"language,omitempty"`
	Description     string   `json:"description,omitempty"`
	Subjects        []string `json:"subjects,omitempty"`
	CoverPage       int      `json:"cover_page,omitempty"`
}

// ToCStatus represents ToC finding and extraction status.
type ToCStatus struct {
	// Finder stage
	FinderStarted  bool `json:"finder_started"`
	FinderComplete bool `json:"finder_complete"`
	FinderFailed   bool `json:"finder_failed"`
	Found          bool `json:"found"`
	StartPage      int  `json:"start_page,omitempty"`
	EndPage        int  `json:"end_page,omitempty"`

	// Extract stage
	ExtractStarted  bool `json:"extract_started"`
	ExtractComplete bool `json:"extract_complete"`
	ExtractFailed   bool `json:"extract_failed"`

	// Link stage
	LinkStarted  bool `json:"link_started"`
	LinkComplete bool `json:"link_complete"`
	LinkFailed   bool `json:"link_failed"`
	LinkRetries  int  `json:"link_retries"`

	// Finalize stage (overall)
	FinalizeStarted  bool `json:"finalize_started"`
	FinalizeComplete bool `json:"finalize_complete"`
	FinalizeFailed   bool `json:"finalize_failed"`
	FinalizeRetries  int  `json:"finalize_retries"`

	// Finalize sub-phases: Pattern Analysis → Chapter Discovery → Gap Validation
	PatternComplete   bool                    `json:"pattern_complete"`              // Pattern analysis done (pattern_analysis_json exists)
	PatternAnalysis   *PatternAnalysisResult  `json:"pattern_analysis,omitempty"`    // Full pattern analysis result
	PatternsFound     int                     `json:"patterns_found"`                // Number of patterns discovered
	ExcludedRanges    int                     `json:"excluded_ranges"`               // Number of excluded page ranges
	EntriesToFind     int                     `json:"entries_to_find"`               // From pattern analysis (how many should be discovered)
	EntriesDiscovered int                     `json:"entries_discovered"`            // Actually discovered (source="discovered")
	DiscoverComplete  bool                    `json:"discover_complete"`             // All entries discovered
	ValidateComplete  bool                    `json:"validate_complete"`             // Gap validation done (same as FinalizeComplete for now)

	// Entries (when extracted)
	EntryCount    int        `json:"entry_count"`
	EntriesLinked int        `json:"entries_linked"`
	Entries       []ToCEntry `json:"entries,omitempty"`

	CostUSD float64 `json:"cost_usd"`
}

// StructureStatus represents book structure building status.
type StructureStatus struct {
	Started      bool    `json:"started"`
	Complete     bool    `json:"complete"`
	Failed       bool    `json:"failed"`
	Retries      int     `json:"retries"`
	CostUSD      float64 `json:"cost_usd"`
	ChapterCount int     `json:"chapter_count,omitempty"`

	// Phase tracking (build -> extract -> classify -> polish -> finalize)
	Phase             string `json:"phase,omitempty"`
	ChaptersTotal     int    `json:"chapters_total,omitempty"`
	ChaptersExtracted int    `json:"chapters_extracted,omitempty"`
	ChaptersPolished  int    `json:"chapters_polished,omitempty"`
	PolishFailed      int    `json:"polish_failed,omitempty"`
}

// ToCEntry represents a single ToC entry.
type ToCEntry struct {
	EntryNumber       string `json:"entry_number,omitempty"`
	Title             string `json:"title"`
	Level             int    `json:"level"`
	LevelName         string `json:"level_name,omitempty"`
	PrintedPageNumber string `json:"printed_page_number,omitempty"`
	SortOrder         int    `json:"sort_order"`
	ActualPageNum     int    `json:"actual_page_num,omitempty"`
	IsLinked          bool   `json:"is_linked"`
	Source            string `json:"source,omitempty"` // "extracted" or "discovered"
}

// PatternAnalysisResult contains the full pattern analysis output.
type PatternAnalysisResult struct {
	Reasoning      string              `json:"reasoning"`
	Patterns       []DiscoveredPattern `json:"patterns"`
	ExcludedRanges []ExcludedRange     `json:"excluded_ranges"`
}

// DiscoveredPattern represents a pattern found by the analyzer.
type DiscoveredPattern struct {
	PatternType   string `json:"pattern_type"`
	LevelName     string `json:"level_name"`
	HeadingFormat string `json:"heading_format"`
	RangeStart    string `json:"range_start"`
	RangeEnd      string `json:"range_end"`
	Level         int    `json:"level"`
	Reasoning     string `json:"reasoning"`
}

// ExcludedRange represents a page range excluded from pattern search.
type ExcludedRange struct {
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"`
}

// AgentLogSummary is a brief summary of an agent log.
type AgentLogSummary struct {
	ID          string `json:"id"`
	AgentType   string `json:"agent_type"`
	StartedAt   string `json:"started_at"`
	CompletedAt string `json:"completed_at,omitempty"`
	Iterations  int    `json:"iterations"`
	Success     bool   `json:"success"`
	Error       string `json:"error,omitempty"`
}

// DetailedJobStatusEndpoint handles GET /api/jobs/status/{book_id}/detailed.
type DetailedJobStatusEndpoint struct{}

func (e *DetailedJobStatusEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/jobs/status/{book_id}/detailed", e.handler
}

func (e *DetailedJobStatusEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get detailed job status for a book
//	@Description	Get comprehensive processing status including per-provider OCR progress, costs, metadata, and ToC details
//	@Tags			jobs
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		200		{object}	DetailedJobStatusResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/jobs/status/{book_id}/detailed [get]
func (e *DetailedJobStatusEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	defraClient := svcctx.DefraClientFrom(r.Context())
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	resp, err := getDetailedStatus(r.Context(), defraClient, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	// Overlay live status if a job is running (more up-to-date progress counts)
	if scheduler := svcctx.SchedulerFrom(r.Context()); scheduler != nil {
		if job := scheduler.GetJobByBookID(bookID); job != nil {
			if provider, ok := job.(jobs.LiveStatusProvider); ok {
				if live := provider.LiveStatus(); live != nil {
					// Override page progress with live counts
					resp.Stages.OCR.Complete = live.OcrComplete

					// Override operation states
					resp.Metadata.Complete = live.MetadataComplete
					resp.ToC.Found = live.TocFound
					resp.ToC.ExtractComplete = live.TocExtracted
					resp.ToC.LinkComplete = live.TocLinked
					resp.ToC.FinalizeComplete = live.TocFinalized
					resp.Structure.Started = live.StructureStarted
					resp.Structure.Complete = live.StructureComplete

					// Overlay costs from write-through cache if available
					if live.CostsByStage != nil {
						for stage, cost := range live.CostsByStage {
							switch stage {
							case "metadata":
								resp.Metadata.CostUSD = cost
							case "pattern_analysis":
								resp.Stages.PatternAnalysis.CostUSD = cost
							case "toc", "toc_finder", "toc_extract", "link_toc":
								resp.ToC.CostUSD += cost
							case "structure_classify", "structure_polish":
								resp.Structure.CostUSD += cost
							default:
								// Check if this is an OCR provider
								if _, exists := resp.OcrProgress[stage]; exists {
									resp.Stages.OCR.CostByProvider[stage] = cost
									if prog := resp.OcrProgress[stage]; prog.Complete > 0 {
										prog.CostUSD = cost
										resp.OcrProgress[stage] = prog
									}
								}
							}
						}
						// Recalculate total OCR cost
						resp.Stages.OCR.TotalCostUSD = 0
						for _, cost := range resp.Stages.OCR.CostByProvider {
							resp.Stages.OCR.TotalCostUSD += cost
						}
					}
				}
			}
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *DetailedJobStatusEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "status-detailed <book_id>",
		Short: "Get detailed job status for a book",
		Long: `Get comprehensive processing status including:
- Per-provider OCR progress and costs
- Metadata extraction status and extracted data
- ToC finder and extraction status with entries
- Agent execution logs`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp DetailedJobStatusResponse
			if err := client.Get(ctx, fmt.Sprintf("/api/jobs/status/%s/detailed", bookID), &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// getDetailedStatus fetches comprehensive status from DefraDB
func getDetailedStatus(ctx context.Context, client *defra.Client, bookID string) (*DetailedJobStatusResponse, error) {
	resp := &DetailedJobStatusResponse{
		BookID:      bookID,
		OcrProgress: make(map[string]ProviderProgress),
	}
	resp.Stages.OCR.CostByProvider = make(map[string]float64)

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
		return nil, fmt.Errorf("failed to query book: %w", err)
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
					Reasoning     string `json:"reasoning"`
					Patterns      []struct {
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

	// Set totals for stages
	resp.Stages.OCR.Total = resp.TotalPages

	// Query pages for completion counts
	pageQuery := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			ocr_complete
		}
	}`, bookID)

	pageResp, err := client.Execute(ctx, pageQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query pages: %w", err)
	}

	if pages, ok := pageResp.Data["Page"].([]any); ok {
		for _, p := range pages {
			page, ok := p.(map[string]any)
			if !ok {
				continue
			}
			if ocrComplete, ok := page["ocr_complete"].(bool); ok && ocrComplete {
				resp.Stages.OCR.Complete++
			}
		}
	}

	// Query OCR results for per-provider progress
	ocrQuery := fmt.Sprintf(`{
		OcrResult(filter: {page: {book_id: {_eq: "%s"}}}) {
			provider
		}
	}`, bookID)

	ocrResp, err := client.Execute(ctx, ocrQuery, nil)
	if err == nil {
		providerCounts := make(map[string]int)
		if results, ok := ocrResp.Data["OcrResult"].([]any); ok {
			for _, r := range results {
				if result, ok := r.(map[string]any); ok {
					if provider, ok := result["provider"].(string); ok {
						providerCounts[provider]++
					}
				}
			}
		}
		for provider, count := range providerCounts {
			resp.OcrProgress[provider] = ProviderProgress{
				Complete: count,
				Total:    resp.TotalPages,
			}
		}
	}

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

	// Query costs from metrics
	metricsQuery := svcctx.MetricsQueryFrom(ctx)
	if metricsQuery != nil {
		if costByOp, err := metricsQuery.CostByOperationType(ctx, metrics.Filter{BookID: bookID}); err == nil {
			// OCR costs by provider
			for provider := range resp.OcrProgress {
				if cost, ok := costByOp[provider]; ok {
					resp.Stages.OCR.CostByProvider[provider] = cost
					resp.Stages.OCR.TotalCostUSD += cost
					if prog, ok := resp.OcrProgress[provider]; ok {
						prog.CostUSD = cost
						resp.OcrProgress[provider] = prog
					}
				}
			}

			// Pattern Analysis cost
			if cost, ok := costByOp["pattern_analysis"]; ok {
				resp.Stages.PatternAnalysis.CostUSD = cost
			}

			// Metadata cost
			if cost, ok := costByOp["metadata"]; ok {
				resp.Metadata.CostUSD = cost
			}

			// ToC costs
			if cost, ok := costByOp["toc"]; ok {
				resp.ToC.CostUSD = cost
			}
			if cost, ok := costByOp["finder"]; ok {
				resp.ToC.CostUSD += cost
			}

			// Structure cost
			if cost, ok := costByOp["structure"]; ok {
				resp.Structure.CostUSD = cost
			}
		}
	}

	// Query agent logs
	agentQuery := fmt.Sprintf(`{
		AgentRun(filter: {book_id: {_eq: "%s"}}) {
			_docID
			agent_type
			started_at
			completed_at
			iterations
			success
			error
		}
	}`, bookID)

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

	return resp, nil
}
