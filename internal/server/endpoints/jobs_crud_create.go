package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateJobRequest is the request body for creating a job.
type CreateJobRequest struct {
	JobType  string         `json:"job_type"`
	Metadata map[string]any `json:"metadata,omitempty"`
}

// CreateJobResponse is the response for creating a job.
type CreateJobResponse struct {
	ID string `json:"id"`
}

// CreateJobEndpoint handles POST /api/jobs.
type CreateJobEndpoint struct{}

func (e *CreateJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/jobs", e.handler
}

func (e *CreateJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Create a job
//	@Description	Create a new job of the specified type
//	@Tags			jobs
//	@Accept			json
//	@Produce		json
//	@Param			request	body		CreateJobRequest	true	"Job creation request"
//	@Success		201		{object}	CreateJobResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/jobs [post]
func (e *CreateJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	var req CreateJobRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if req.JobType == "" {
		writeError(w, http.StatusBadRequest, "job_type is required")
		return
	}

	jm := svcctx.JobManagerFrom(r.Context())
	if jm == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	id, err := jm.Create(r.Context(), req.JobType, req.Metadata)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, CreateJobResponse{ID: id})
}

func (e *CreateJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	var jobType string
	cmd := &cobra.Command{
		Use:   "create",
		Short: "Create a new job",
		RunE: func(cmd *cobra.Command, args []string) error {
			if jobType == "" {
				return fmt.Errorf("--type is required")
			}
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp CreateJobResponse
			if err := client.Post(ctx, "/api/jobs", CreateJobRequest{JobType: jobType}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&jobType, "type", "", "Job type (required)")
	return cmd
}
