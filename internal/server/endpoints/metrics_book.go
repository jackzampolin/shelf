package endpoints

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// BookCostEndpoint handles GET /api/books/{id}/cost.
type BookCostEndpoint struct{}

func (e *BookCostEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}/cost", e.handler
}

func (e *BookCostEndpoint) RequiresInit() bool { return true }

func (e *BookCostEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	// Check for breakdown
	byStage := r.URL.Query().Get("by") == "stage"

	var resp MetricsCostResponse
	var err error

	if byStage {
		resp.Breakdown, err = query.BookStageBreakdown(r.Context(), bookID)
		if err == nil {
			for _, v := range resp.Breakdown {
				resp.TotalCostUSD += v
			}
		}
	} else {
		resp.TotalCostUSD, err = query.BookCost(r.Context(), bookID)
	}

	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *BookCostEndpoint) Command(getServerURL func() string) *cobra.Command {
	var byStage bool

	cmd := &cobra.Command{
		Use:   "cost <book_id>",
		Short: "Get cost for a book",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			path := "/api/books/" + bookID + "/cost"
			if byStage {
				path += "?by=stage"
			}

			client := api.NewClient(getServerURL())
			var resp MetricsCostResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			fmt.Printf("Book Cost: $%.4f\n", resp.TotalCostUSD)

			if len(resp.Breakdown) > 0 {
				fmt.Printf("\nBreakdown by stage:\n")
				for k, v := range resp.Breakdown {
					fmt.Printf("  %-20s  $%.4f\n", k, v)
				}
			}

			return nil
		},
	}

	cmd.Flags().BoolVar(&byStage, "by-stage", false, "Show breakdown by stage")

	return cmd
}
