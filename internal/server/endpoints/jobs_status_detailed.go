package endpoints

import (
	"context"
	"fmt"
	"net/http"
	"strconv"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
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
		Quarantined    int                `json:"quarantined,omitempty"`
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
	PatternComplete   bool                   `json:"pattern_complete"`           // Pattern analysis done (pattern_analysis_json exists)
	PatternAnalysis   *PatternAnalysisResult `json:"pattern_analysis,omitempty"` // Full pattern analysis result
	PatternsFound     int                    `json:"patterns_found"`             // Number of patterns discovered
	ExcludedRanges    int                    `json:"excluded_ranges"`            // Number of excluded page ranges
	EntriesToFind     int                    `json:"entries_to_find"`            // From pattern analysis (how many should be discovered)
	EntriesDiscovered int                    `json:"entries_discovered"`         // Actually discovered (source="discovered")
	DiscoverComplete  bool                   `json:"discover_complete"`          // All entries discovered
	ValidateComplete  bool                   `json:"validate_complete"`          // Gap validation done (same as FinalizeComplete for now)

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

const defaultDetailedStatusAgentLogLimit = 100

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

	agentLogLimit := defaultDetailedStatusAgentLogLimit
	if raw := r.URL.Query().Get("agent_log_limit"); raw != "" {
		parsed, parseErr := strconv.Atoi(raw)
		if parseErr != nil || parsed < 0 {
			writeError(w, http.StatusBadRequest, "agent_log_limit must be a non-negative integer")
			return
		}
		agentLogLimit = parsed
	}

	resp, err := getDetailedStatus(r.Context(), defraClient, bookID, agentLogLimit)
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
	var agentLogLimit int
	cmd := &cobra.Command{
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
			if err := client.Get(ctx, fmt.Sprintf("/api/jobs/status/%s/detailed?agent_log_limit=%d", bookID, agentLogLimit), &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().IntVar(&agentLogLimit, "agent-log-limit", defaultDetailedStatusAgentLogLimit, "Maximum recent agent logs to include (0 disables logs)")
	return cmd
}

// getDetailedStatus fetches comprehensive status from DefraDB
func getDetailedStatus(ctx context.Context, client *defra.Client, bookID string, agentLogLimit int) (*DetailedJobStatusResponse, error) {
	resp := &DetailedJobStatusResponse{
		BookID:      bookID,
		OcrProgress: make(map[string]ProviderProgress),
	}
	resp.Stages.OCR.CostByProvider = make(map[string]float64)

	if err := buildMetadataStatus(ctx, client, bookID, resp); err != nil {
		return nil, err
	}
	if err := buildOcrProgress(ctx, client, bookID, resp); err != nil {
		return nil, err
	}
	if err := buildTocStatus(ctx, client, bookID, resp); err != nil {
		return nil, err
	}
	if err := buildStructureStatus(ctx, client, bookID, resp); err != nil {
		return nil, err
	}
	if err := buildCostBreakdown(ctx, bookID, resp); err != nil {
		return nil, err
	}
	if err := loadAgentLogs(ctx, client, bookID, resp, agentLogLimit); err != nil {
		return nil, err
	}

	return resp, nil
}
