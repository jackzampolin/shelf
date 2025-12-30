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

// GetJobResponse includes the job record plus live status if available.
type GetJobResponse struct {
	*jobs.Record

	// Live status fields (only populated for running jobs)
	LiveStatus     map[string]string              `json:"live_status,omitempty"`
	Progress       map[string]jobs.ProviderProgress `json:"progress,omitempty"`
	WorkerStatus   map[string]jobs.WorkerStatusInfo `json:"worker_status,omitempty"`
	PendingUnits   int                            `json:"pending_units,omitempty"`
}

// GetJobEndpoint handles GET /api/jobs/{id}.
type GetJobEndpoint struct{}

func (e *GetJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/jobs/{id}", e.handler
}

func (e *GetJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get job by ID
//	@Description	Get detailed job information including live status for running jobs
//	@Tags			jobs
//	@Produce		json
//	@Param			id	path		string	true	"Job ID"
//	@Success		200	{object}	GetJobResponse
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/jobs/{id} [get]
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

	resp := GetJobResponse{Record: job}

	// If job is running, try to get live status from scheduler
	if job.Status == jobs.StatusRunning {
		scheduler := svcctx.SchedulerFrom(r.Context())
		if scheduler != nil {
			// Get live job status (includes pending_units)
			if liveStatus, err := scheduler.JobStatus(r.Context(), id); err == nil {
				resp.LiveStatus = liveStatus
				if pendingStr, ok := liveStatus["pending_units"]; ok {
					fmt.Sscanf(pendingStr, "%d", &resp.PendingUnits)
				}
			}

			// Get per-provider progress
			if progress := scheduler.JobProgress(id); progress != nil {
				resp.Progress = progress
			}

			// Get worker status (queue depths, rate limiters)
			resp.WorkerStatus = scheduler.WorkerStatus()
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *GetJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <id>",
		Short: "Get a job by ID",
		Long: `Get detailed information about a job.

For running jobs, this includes:
- Live status: current progress counts (extract, ocr, blend, label complete)
- Progress: per-provider completion counts (e.g., each OCR provider)
- Worker status: queue depths and rate limiter info
- Pending units: number of work units still in flight`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp GetJobResponse
			if err := client.Get(ctx, "/api/jobs/"+args[0], &resp); err != nil {
				return err
			}
			return api.Output(resp)
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

// DeleteJobEndpoint handles DELETE /api/jobs/{id}.
type DeleteJobEndpoint struct{}

func (e *DeleteJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "DELETE", "/api/jobs/{id}", e.handler
}

func (e *DeleteJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Delete a job
//	@Description	Delete a job by ID
//	@Tags			jobs
//	@Param			id	path	string	true	"Job ID"
//	@Success		204	"No Content"
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/jobs/{id} [delete]
func (e *DeleteJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
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

	if err := jm.Delete(r.Context(), id); err != nil {
		if errors.Is(err, jobs.ErrNotFound) {
			writeError(w, http.StatusNotFound, "job not found")
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (e *DeleteJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "delete <id>",
		Short: "Delete a job by ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			if err := client.Delete(ctx, "/api/jobs/"+args[0]); err != nil {
				return err
			}
			fmt.Println("Job deleted successfully")
			return nil
		},
	}
}
