package endpoints

import (
	"fmt"
	"net/http"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MetricsSummaryResponse is the response for summary queries.
type MetricsSummaryResponse struct {
	Count            int     `json:"count"`
	TotalCostUSD     float64 `json:"total_cost_usd"`
	TotalTokens      int     `json:"total_tokens"`
	TotalTimeSeconds float64 `json:"total_time_seconds"`
	SuccessCount     int     `json:"success_count"`
	ErrorCount       int     `json:"error_count"`
	AvgCostUSD       float64 `json:"avg_cost_usd"`
	AvgTokens        float64 `json:"avg_tokens"`
	AvgTimeSeconds   float64 `json:"avg_time_seconds"`
}

// MetricsSummaryEndpoint handles GET /api/metrics/summary.
type MetricsSummaryEndpoint struct{}

func (e *MetricsSummaryEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/metrics/summary", e.handler
}

func (e *MetricsSummaryEndpoint) RequiresInit() bool { return true }

func (e *MetricsSummaryEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	defraClient := svcctx.DefraClientFrom(r.Context())
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	query := metrics.NewQuery(defraClient)

	// Build filter from query params
	f := metrics.Filter{
		JobID:    r.URL.Query().Get("job_id"),
		BookID:   r.URL.Query().Get("book_id"),
		Stage:    r.URL.Query().Get("stage"),
		Provider: r.URL.Query().Get("provider"),
		Model:    r.URL.Query().Get("model"),
	}

	summary, err := query.GetSummary(r.Context(), f)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, MetricsSummaryResponse{
		Count:            summary.Count,
		TotalCostUSD:     summary.TotalCostUSD,
		TotalTokens:      summary.TotalTokens,
		TotalTimeSeconds: summary.TotalTime.Seconds(),
		SuccessCount:     summary.SuccessCount,
		ErrorCount:       summary.ErrorCount,
		AvgCostUSD:       summary.AvgCostUSD,
		AvgTokens:        summary.AvgTokens,
		AvgTimeSeconds:   summary.AvgTimeSeconds,
	})
}

func (e *MetricsSummaryEndpoint) Command(getServerURL func() string) *cobra.Command {
	var bookID, stage, provider, model string

	cmd := &cobra.Command{
		Use:   "summary",
		Short: "Get metrics summary",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			// Build query string
			path := "/api/metrics/summary?"
			params := []string{}
			if bookID != "" {
				params = append(params, "book_id="+bookID)
			}
			if stage != "" {
				params = append(params, "stage="+stage)
			}
			if provider != "" {
				params = append(params, "provider="+provider)
			}
			if model != "" {
				params = append(params, "model="+model)
			}
			for i, p := range params {
				if i > 0 {
					path += "&"
				}
				path += p
			}

			var resp MetricsSummaryResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			fmt.Printf("Metrics Summary\n")
			fmt.Printf("===============\n")
			fmt.Printf("  Count:       %d\n", resp.Count)
			fmt.Printf("  Success:     %d\n", resp.SuccessCount)
			fmt.Printf("  Errors:      %d\n", resp.ErrorCount)
			fmt.Println()
			fmt.Printf("  Total Cost:  $%.4f\n", resp.TotalCostUSD)
			fmt.Printf("  Avg Cost:    $%.6f\n", resp.AvgCostUSD)
			fmt.Println()
			fmt.Printf("  Total Tokens: %d\n", resp.TotalTokens)
			fmt.Printf("  Avg Tokens:   %.1f\n", resp.AvgTokens)
			fmt.Println()
			fmt.Printf("  Total Time:   %s\n", time.Duration(resp.TotalTimeSeconds*float64(time.Second)))
			fmt.Printf("  Avg Time:     %.2fs\n", resp.AvgTimeSeconds)

			return nil
		},
	}

	cmd.Flags().StringVar(&bookID, "book", "", "Filter by book ID")
	cmd.Flags().StringVar(&stage, "stage", "", "Filter by stage")
	cmd.Flags().StringVar(&provider, "provider", "", "Filter by provider")
	cmd.Flags().StringVar(&model, "model", "", "Filter by model")

	return cmd
}
