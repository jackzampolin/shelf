package endpoints

import (
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MetricsCostResponse is the response for cost queries.
type MetricsCostResponse struct {
	TotalCostUSD float64            `json:"total_cost_usd"`
	Breakdown    map[string]float64 `json:"breakdown,omitempty"`
}

// MetricsCostEndpoint handles GET /api/metrics/cost.
type MetricsCostEndpoint struct{}

func (e *MetricsCostEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/metrics/cost", e.handler
}

func (e *MetricsCostEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get cost breakdown
//	@Description	Get total cost with optional breakdown by stage/provider/model
//	@Tags			metrics
//	@Produce		json
//	@Param			job_id		query		string	false	"Filter by job ID"
//	@Param			book_id		query		string	false	"Filter by book ID"
//	@Param			stage		query		string	false	"Filter by stage"
//	@Param			provider	query		string	false	"Filter by provider"
//	@Param			model		query		string	false	"Filter by model"
//	@Param			by			query		string	false	"Breakdown by: stage, provider, or model"
//	@Success		200			{object}	MetricsCostResponse
//	@Failure		500			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/metrics/cost [get]
func (e *MetricsCostEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	// Check for breakdown type
	byStage := r.URL.Query().Get("by") == "stage"
	byProvider := r.URL.Query().Get("by") == "provider"
	byModel := r.URL.Query().Get("by") == "model"

	var resp MetricsCostResponse
	var err error

	if byStage {
		// List and aggregate by stage
		metricsList, listErr := query.List(r.Context(), f, 0)
		if listErr != nil {
			writeError(w, http.StatusInternalServerError, listErr.Error())
			return
		}
		resp.Breakdown = make(map[string]float64)
		for _, m := range metricsList {
			resp.Breakdown[m.Stage] += m.CostUSD
			resp.TotalCostUSD += m.CostUSD
		}
	} else if byProvider {
		resp.Breakdown, err = query.CostByProvider(r.Context(), f)
		if err == nil {
			for _, v := range resp.Breakdown {
				resp.TotalCostUSD += v
			}
		}
	} else if byModel {
		resp.Breakdown, err = query.CostByModel(r.Context(), f)
		if err == nil {
			for _, v := range resp.Breakdown {
				resp.TotalCostUSD += v
			}
		}
	} else {
		resp.TotalCostUSD, err = query.TotalCost(r.Context(), f)
	}

	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *MetricsCostEndpoint) Command(getServerURL func() string) *cobra.Command {
	var bookID, stage, provider, model, by string

	cmd := &cobra.Command{
		Use:   "cost",
		Short: "Get cost summary",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			// Build query string
			path := "/api/metrics/cost?"
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
			if by != "" {
				params = append(params, "by="+by)
			}
			for i, p := range params {
				if i > 0 {
					path += "&"
				}
				path += p
			}

			var resp MetricsCostResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}

	cmd.Flags().StringVar(&bookID, "book", "", "Filter by book ID")
	cmd.Flags().StringVar(&stage, "stage", "", "Filter by stage")
	cmd.Flags().StringVar(&provider, "provider", "", "Filter by provider")
	cmd.Flags().StringVar(&model, "model", "", "Filter by model")
	cmd.Flags().StringVar(&by, "by", "", "Breakdown by: stage, provider, or model")

	return cmd
}
