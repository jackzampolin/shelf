package endpoints

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"net/url"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
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

// GetJobEndpoint handles GET /api/jobs/{id}.
type GetJobEndpoint struct{}

func (e *GetJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/jobs/{id}", e.handler
}

func (e *GetJobEndpoint) RequiresInit() bool { return true }

func (e *GetJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "job id is required")
		return
	}

	jm := svcctx.JobManagerFrom(r.Context())
	if jm == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	job, err := jm.Get(r.Context(), id)
	if err != nil {
		if errors.Is(err, jobs.ErrNotFound) {
			writeError(w, http.StatusNotFound, "job not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	writeJSON(w, http.StatusOK, job)
}

func (e *GetJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <id>",
		Short: "Get a job by ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var job jobs.Record
			if err := client.Get(ctx, "/api/jobs/"+args[0], &job); err != nil {
				return err
			}
			return api.Output(job)
		},
	}
}

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
