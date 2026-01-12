package endpoints

import (
	"errors"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GetJobResponse includes the job record plus live status if available.
type GetJobResponse struct {
	*jobs.Record

	// Live status fields (only populated for running jobs)
	LiveStatus   map[string]string                `json:"live_status,omitempty"`
	Progress     map[string]jobs.ProviderProgress `json:"progress,omitempty"`
	WorkerStatus map[string]jobs.WorkerStatusInfo `json:"worker_status,omitempty"`
	PendingUnits int                              `json:"pending_units,omitempty"`
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
