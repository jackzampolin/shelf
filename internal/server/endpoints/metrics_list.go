package endpoints

import (
	"fmt"
	"net/http"
	"strconv"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ListMetricsResponse is the response for listing metrics.
type ListMetricsResponse struct {
	Metrics []metrics.Metric `json:"metrics"`
	Count   int              `json:"count"`
}

// ListMetricsEndpoint handles GET /api/metrics.
type ListMetricsEndpoint struct{}

func (e *ListMetricsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/metrics", e.handler
}

func (e *ListMetricsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List metrics
//	@Description	List LLM/OCR call metrics with optional filtering
//	@Tags			metrics
//	@Produce		json
//	@Param			job_id		query		string	false	"Filter by job ID"
//	@Param			book_id		query		string	false	"Filter by book ID"
//	@Param			stage		query		string	false	"Filter by stage"
//	@Param			provider	query		string	false	"Filter by provider"
//	@Param			model		query		string	false	"Filter by model"
//	@Param			limit		query		int		false	"Maximum results (default 100)"
//	@Success		200			{object}	ListMetricsResponse
//	@Failure		500			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/metrics [get]
func (e *ListMetricsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	// Parse limit
	limit := 100
	if l := r.URL.Query().Get("limit"); l != "" {
		if parsed, err := strconv.Atoi(l); err == nil && parsed > 0 {
			limit = parsed
		}
	}

	result, err := query.List(r.Context(), f, limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, ListMetricsResponse{
		Metrics: result,
		Count:   len(result),
	})
}

func (e *ListMetricsEndpoint) Command(getServerURL func() string) *cobra.Command {
	var bookID, stage, provider, model string
	var limit int

	cmd := &cobra.Command{
		Use:   "list",
		Short: "List metrics",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			// Build query string
			path := "/api/metrics?"
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
			if limit > 0 {
				params = append(params, fmt.Sprintf("limit=%d", limit))
			}
			for i, p := range params {
				if i > 0 {
					path += "&"
				}
				path += p
			}

			var resp ListMetricsResponse
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
	cmd.Flags().IntVar(&limit, "limit", 100, "Maximum results")

	return cmd
}
