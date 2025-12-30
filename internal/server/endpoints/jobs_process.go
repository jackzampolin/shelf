package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/process_pages"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// StartJobRequest is the request body for starting a job.
type StartJobRequest struct {
	JobType string `json:"job_type,omitempty"` // Optional: defaults to "process-pages"
}

// StartJobResponse is the response for starting a job.
type StartJobResponse struct {
	JobID   string `json:"job_id"`
	JobType string `json:"job_type"`
	BookID  string `json:"book_id"`
	Status  string `json:"status"`
}

// StartJobEndpoint handles POST /api/jobs/start/{book_id}.
type StartJobEndpoint struct {
	// ProcessPagesConfig holds config for process-pages jobs
	ProcessPagesConfig process_pages.Config
}

func (e *StartJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/jobs/start/{book_id}", e.handler
}

func (e *StartJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Start job for a book
//	@Description	Start processing job (OCR, blend, label) for a book
//	@Tags			jobs
//	@Accept			json
//	@Produce		json
//	@Param			book_id	path		string			true	"Book ID"
//	@Param			request	body		StartJobRequest	false	"Optional job type"
//	@Success		202		{object}	StartJobResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/jobs/start/{book_id} [post]
func (e *StartJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	var req StartJobRequest
	if r.Body != nil && r.ContentLength > 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
	}

	jobType := req.JobType
	if jobType == "" {
		jobType = process_pages.JobType
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}

	// Create job based on job type
	var job jobs.Job
	var err error

	switch jobType {
	case process_pages.JobType:
		job, err = process_pages.NewJob(r.Context(), e.ProcessPagesConfig, bookID)
	default:
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unknown job type: %s", jobType))
		return
	}

	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create job: %v", err))
		return
	}

	// Submit to scheduler
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, StartJobResponse{
		JobID:   job.ID(),
		JobType: jobType,
		BookID:  bookID,
		Status:  "queued",
	})
}

func (e *StartJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	var jobType string
	cmd := &cobra.Command{
		Use:   "start <book_id>",
		Short: "Start job processing for a book",
		Long: `Start a processing job for a book.

The default job type is 'process-pages' which processes all pages through
OCR, blend, and label stages, then triggers book-level operations
(metadata extraction, ToC finding).

The command submits a job and returns immediately.
Use 'shelf api jobs get <job-id>' to check progress.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp StartJobResponse
			if err := client.Post(ctx, "/api/jobs/start/"+bookID, StartJobRequest{
				JobType: jobType,
			}, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&jobType, "job-type", process_pages.JobType, "Job type to run")
	return cmd
}

// JobStatusResponse is the response for job status.
type JobStatusResponse struct {
	BookID           string `json:"book_id"`
	JobType          string `json:"job_type"`
	TotalPages       int    `json:"total_pages"`
	OcrComplete      int    `json:"ocr_complete"`
	BlendComplete    int    `json:"blend_complete"`
	LabelComplete    int    `json:"label_complete"`
	MetadataComplete bool   `json:"metadata_complete"`
	TocFound         bool   `json:"toc_found"`
	TocExtracted     bool   `json:"toc_extracted"`
	IsComplete       bool   `json:"is_complete"`
}

// JobStatusEndpoint handles GET /api/jobs/status/{book_id}.
type JobStatusEndpoint struct{}

func (e *JobStatusEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/jobs/status/{book_id}", e.handler
}

func (e *JobStatusEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get job status for a book
//	@Description	Get processing status for a book's jobs
//	@Tags			jobs
//	@Produce		json
//	@Param			book_id		path		string	true	"Book ID"
//	@Param			job_type	query		string	false	"Job type (default: process-pages)"
//	@Success		200			{object}	JobStatusResponse
//	@Failure		400			{object}	ErrorResponse
//	@Failure		500			{object}	ErrorResponse
//	@Failure		503			{object}	ErrorResponse
//	@Router			/api/jobs/status/{book_id} [get]
func (e *JobStatusEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	jobType := r.URL.Query().Get("job_type")
	if jobType == "" {
		jobType = process_pages.JobType
	}

	// Get status based on job type
	var resp JobStatusResponse
	resp.BookID = bookID
	resp.JobType = jobType

	switch jobType {
	case process_pages.JobType:
		status, err := process_pages.GetStatus(r.Context(), bookID)
		if err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to get status: %v", err))
			return
		}
		resp.TotalPages = status.TotalPages
		resp.OcrComplete = status.OcrComplete
		resp.BlendComplete = status.BlendComplete
		resp.LabelComplete = status.LabelComplete
		resp.MetadataComplete = status.MetadataComplete
		resp.TocFound = status.TocFound
		resp.TocExtracted = status.TocExtracted
		resp.IsComplete = status.IsComplete()
	default:
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unknown job type: %s", jobType))
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func (e *JobStatusEndpoint) Command(getServerURL func() string) *cobra.Command {
	var jobType string
	cmd := &cobra.Command{
		Use:   "status <book_id>",
		Short: "Get job status for a book",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			path := fmt.Sprintf("/api/jobs/status/%s", bookID)
			if jobType != process_pages.JobType {
				path += "?job_type=" + jobType
			}

			client := api.NewClient(getServerURL())
			var resp JobStatusResponse
			if err := client.Get(ctx, path, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&jobType, "job-type", process_pages.JobType, "Job type to check")
	return cmd
}
