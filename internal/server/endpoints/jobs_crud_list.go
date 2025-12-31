package endpoints

import (
	"net/http"
	"net/url"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ListJobsResponse is the response for listing jobs.
type ListJobsResponse struct {
	Jobs []*jobs.Record `json:"jobs"`
}

// ListJobsEndpoint handles GET /api/jobs.
type ListJobsEndpoint struct{}

func (e *ListJobsEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/jobs", e.handler
}

func (e *ListJobsEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List jobs
//	@Description	List all jobs with optional filtering
//	@Tags			jobs
//	@Produce		json
//	@Param			status		query		string	false	"Filter by status"
//	@Param			job_type	query		string	false	"Filter by job type"
//	@Success		200			{object}	ListJobsResponse
//	@Failure		500			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/jobs [get]
func (e *ListJobsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	jm := svcctx.JobManagerFrom(r.Context())
	if jm == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	filter := jobs.ListFilter{
		Status:  jobs.Status(r.URL.Query().Get("status")),
		JobType: r.URL.Query().Get("job_type"),
	}

	jobsList, err := jm.List(r.Context(), filter)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, ListJobsResponse{Jobs: jobsList})
}

func (e *ListJobsEndpoint) Command(getServerURL func() string) *cobra.Command {
	var status, jobType string
	cmd := &cobra.Command{
		Use:   "list",
		Short: "List jobs",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			// Build query string
			path := "/api/jobs"
			params := url.Values{}
			if status != "" {
				params.Set("status", status)
			}
			if jobType != "" {
				params.Set("job_type", jobType)
			}
			if len(params) > 0 {
				path += "?" + params.Encode()
			}

			var resp ListJobsResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&status, "status", "", "Filter by status")
	cmd.Flags().StringVar(&jobType, "type", "", "Filter by job type")
	return cmd
}
