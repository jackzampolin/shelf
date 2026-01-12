package endpoints

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MetricsDetailedResponse is the response for detailed metrics with percentiles.
type MetricsDetailedResponse struct {
	BookID string                            `json:"book_id,omitempty"`
	Stages map[string]*metrics.DetailedStats `json:"stages"`
}

// MetricsDetailedEndpoint handles GET /api/metrics/detailed.
type MetricsDetailedEndpoint struct{}

func (e *MetricsDetailedEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/metrics/detailed", e.handler
}

func (e *MetricsDetailedEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get detailed metrics with percentiles
//	@Description	Get detailed metrics including latency percentiles (p50, p95, p99) and token breakdowns per stage
//	@Tags			metrics
//	@Produce		json
//	@Param			book_id	query		string	false	"Filter by book ID"
//	@Success		200		{object}	MetricsDetailedResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/metrics/detailed [get]
func (e *MetricsDetailedEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	defraClient := svcctx.DefraClientFrom(r.Context())
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	bookID := r.URL.Query().Get("book_id")
	query := metrics.NewQuery(defraClient)

	var stages map[string]*metrics.DetailedStats
	var err error

	if bookID != "" {
		// Get stats per stage for this book
		stages, err = query.StageDetailedStats(r.Context(), bookID)
	} else {
		// Get overall stats grouped by stage
		stages, err = query.StageDetailedStats(r.Context(), "")
	}

	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, MetricsDetailedResponse{
		BookID: bookID,
		Stages: stages,
	})
}

func (e *MetricsDetailedEndpoint) Command(getServerURL func() string) *cobra.Command {
	var bookID string

	cmd := &cobra.Command{
		Use:   "detailed",
		Short: "Get detailed metrics with percentiles",
		Long: `Get detailed metrics including latency percentiles (p50, p95, p99)
and token breakdowns (prompt, completion, reasoning) per stage.`,
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			path := "/api/metrics/detailed"
			if bookID != "" {
				path += "?book_id=" + bookID
			}

			var resp MetricsDetailedResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}

	cmd.Flags().StringVar(&bookID, "book", "", "Filter by book ID")

	return cmd
}

// BookMetricsDetailedEndpoint handles GET /api/books/{id}/metrics/detailed.
type BookMetricsDetailedEndpoint struct{}

func (e *BookMetricsDetailedEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}/metrics/detailed", e.handler
}

func (e *BookMetricsDetailedEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get detailed book metrics with percentiles
//	@Description	Get detailed metrics for a specific book including latency percentiles and token breakdowns per stage
//	@Tags			books,metrics
//	@Produce		json
//	@Param			id	path		string	true	"Book ID"
//	@Success		200	{object}	MetricsDetailedResponse
//	@Failure		400	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/books/{id}/metrics/detailed [get]
func (e *BookMetricsDetailedEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book id is required")
		return
	}

	defraClient := svcctx.DefraClientFrom(r.Context())
	if defraClient == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	query := metrics.NewQuery(defraClient)
	stages, err := query.StageDetailedStats(r.Context(), bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, MetricsDetailedResponse{
		BookID: bookID,
		Stages: stages,
	})
}

func (e *BookMetricsDetailedEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "metrics-detailed <book_id>",
		Short: "Get detailed metrics for a book",
		Long: `Get detailed metrics for a specific book including latency percentiles
(p50, p95, p99) and token breakdowns (prompt, completion, reasoning) per stage.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp MetricsDetailedResponse
			if err := client.Get(ctx, fmt.Sprintf("/api/books/%s/metrics/detailed", bookID), &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}
