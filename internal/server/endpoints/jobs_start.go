package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common_structure"
	"github.com/jackzampolin/shelf/internal/jobs/label_book"
	"github.com/jackzampolin/shelf/internal/jobs/link_toc"
	"github.com/jackzampolin/shelf/internal/jobs/metadata_book"
	"github.com/jackzampolin/shelf/internal/jobs/ocr_book"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/jobs/toc_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// StartJobRequest is the request body for starting a job.
type StartJobRequest struct {
	JobType string `json:"job_type,omitempty"` // Optional: defaults to "process-book"
	Force   bool   `json:"force,omitempty"`    // Optional: force restart even if already complete
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
	// ProcessBookConfig holds config for process-book jobs
	ProcessBookConfig process_book.Config
	// OcrBookConfig holds config for ocr-book jobs
	OcrBookConfig ocr_book.Config
	// LabelBookConfig holds config for label-book jobs
	LabelBookConfig label_book.Config
	// MetadataBookConfig holds config for metadata-book jobs
	MetadataBookConfig metadata_book.Config
	// TocBookConfig holds config for toc-book jobs
	TocBookConfig toc_book.Config
	// LinkTocConfig holds config for link-toc jobs
	LinkTocConfig link_toc.Config
	// CommonStructureConfig holds config for common-structure jobs
	CommonStructureConfig common_structure.Config
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
		jobType = process_book.JobType
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
	case process_book.JobType:
		job, err = process_book.NewJob(r.Context(), e.ProcessBookConfig, bookID)
	case ocr_book.JobType:
		job, err = ocr_book.NewJob(r.Context(), e.OcrBookConfig, bookID)
	case label_book.JobType:
		job, err = label_book.NewJob(r.Context(), e.LabelBookConfig, bookID)
	case metadata_book.JobType:
		job, err = metadata_book.NewJob(r.Context(), e.MetadataBookConfig, bookID)
	case toc_book.JobType:
		job, err = toc_book.NewJob(r.Context(), e.TocBookConfig, bookID)
	case link_toc.JobType:
		// Copy config and apply force flag from request
		cfg := e.LinkTocConfig
		cfg.Force = req.Force
		job, err = link_toc.NewJob(r.Context(), cfg, bookID)
	case common_structure.JobType:
		job, err = common_structure.NewJob(r.Context(), e.CommonStructureConfig, bookID)
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

The default job type is 'process-book' which processes all pages through
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
	cmd.Flags().StringVar(&jobType, "job-type", process_book.JobType, "Job type to run")
	return cmd
}
