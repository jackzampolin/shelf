package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// UpdateJobRequest is the request body for updating a job.
type UpdateJobRequest struct {
	Status   string         `json:"status,omitempty"`
	Error    string         `json:"error,omitempty"`
	Metadata map[string]any `json:"metadata,omitempty"`
}

// UpdateJobEndpoint handles PATCH /api/jobs/{id}.
type UpdateJobEndpoint struct{}

func (e *UpdateJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "PATCH", "/api/jobs/{id}", e.handler
}

func (e *UpdateJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Update a job
//	@Description	Update job status or metadata
//	@Tags			jobs
//	@Accept			json
//	@Produce		json
//	@Param			id		path		string				true	"Job ID"
//	@Param			request	body		UpdateJobRequest	true	"Update request"
//	@Success		200		{object}	jobs.Record
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/jobs/{id} [patch]
func (e *UpdateJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "job id is required")
		return
	}

	var req UpdateJobRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	jm := svcctx.JobManagerFrom(r.Context())
	if jm == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	// Update status if provided
	if req.Status != "" {
		if err := jm.UpdateStatus(r.Context(), id, jobs.Status(req.Status), req.Error); err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
	}

	// Update metadata if provided
	if req.Metadata != nil {
		if err := jm.UpdateMetadata(r.Context(), id, req.Metadata); err != nil {
			writeError(w, http.StatusInternalServerError, err.Error())
			return
		}
	}

	// Return updated job
	job, err := jm.Get(r.Context(), id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, job)
}

func (e *UpdateJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	var status, jobError string
	cmd := &cobra.Command{
		Use:   "update <id>",
		Short: "Update a job",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if status == "" && jobError == "" {
				return fmt.Errorf("at least --status or --error must be specified")
			}
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var job jobs.Record
			req := UpdateJobRequest{Status: status, Error: jobError}
			if err := client.Patch(ctx, "/api/jobs/"+args[0], req, &job); err != nil {
				return err
			}
			return api.Output(job)
		},
	}
	cmd.Flags().StringVar(&status, "status", "", "New status")
	cmd.Flags().StringVar(&jobError, "error", "", "Error message (for failed status)")
	return cmd
}
