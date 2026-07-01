package endpoints

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// StartJobRequest is the request body for starting a job.
type StartJobRequest struct {
	JobType   string `json:"job_type,omitempty"`   // Optional: defaults to "process-book"
	Force     bool   `json:"force,omitempty"`      // Optional: force restart even if already complete
	ResetFrom string `json:"reset_from,omitempty"` // Optional: reset this operation and downstream deps before starting
	Variant   string `json:"variant,omitempty"`    // Optional: pipeline variant (standard, photo-book, text-only, ocr-only)
}

// StartJobResponse is the response for starting a job.
type StartJobResponse struct {
	JobID   string `json:"job_id"`
	JobType string `json:"job_type"`
	BookID  string `json:"book_id"`
	Status  string `json:"status"`
}

// StartJobEndpoint handles POST /api/jobs/start/{book_id}.
// Job configs are read from DefraDB at request time, so settings changes
// via the UI take effect immediately.
type StartJobEndpoint struct{}

func (e *StartJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/jobs/start/{book_id}", e.handler
}

func (e *StartJobEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Start job for a book
//	@Description	Start processing job for a book
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

	resp, status, err := startJobForBook(r.Context(), bookID, req)
	if err != nil {
		writeError(w, status, err.Error())
		return
	}

	writeJSON(w, status, resp)
}

func startJobForBook(ctx context.Context, bookID string, req StartJobRequest) (*StartJobResponse, int, error) {
	jobType := req.JobType
	if jobType == "" {
		jobType = process_book.JobType
	}

	scheduler := svcctx.SchedulerFrom(ctx)
	if scheduler == nil {
		return nil, http.StatusServiceUnavailable, fmt.Errorf("scheduler not initialized")
	}

	// Get config store and create builder to read configs at request time
	configStore := svcctx.ConfigStoreFrom(ctx)
	if configStore == nil {
		return nil, http.StatusServiceUnavailable, fmt.Errorf("config store not initialized")
	}
	builder := jobcfg.NewBuilder(configStore)

	// Create job - only process_book is supported
	var job jobs.Job
	var err error

	if jobType != process_book.JobType {
		return nil, http.StatusBadRequest, fmt.Errorf("unknown job type: %s (only 'process-book' is supported)", jobType)
	}

	if !req.Force {
		if existing := scheduler.GetJobByBookIDAndType(bookID, jobType); existing != nil {
			return nil, http.StatusConflict, fmt.Errorf("%s job already active for book %s: %s", jobType, bookID, existing.ID())
		}
		if jobManager := svcctx.JobManagerFrom(ctx); jobManager != nil {
			running, err := jobManager.List(ctx, jobs.ListFilter{
				Status:  jobs.StatusRunning,
				JobType: jobType,
				BookID:  bookID,
				Limit:   1,
			})
			if err != nil {
				return nil, http.StatusInternalServerError, fmt.Errorf("failed to check running jobs: %v", err)
			}
			if len(running) > 0 {
				return nil, http.StatusConflict, fmt.Errorf("%s job already running for book %s: %s", jobType, bookID, running[0].ID)
			}
		}
	} else {
		reason := fmt.Sprintf("cancelled by forced %s restart for book %s", jobType, bookID)
		scheduler.CancelActiveJobsByBookIDAndType(ctx, bookID, jobType, reason)
		if jobManager := svcctx.JobManagerFrom(ctx); jobManager != nil {
			running, err := jobManager.List(ctx, jobs.ListFilter{
				Status:  jobs.StatusRunning,
				JobType: jobType,
				BookID:  bookID,
				Limit:   100,
			})
			if err != nil {
				return nil, http.StatusInternalServerError, fmt.Errorf("failed to list running jobs for forced restart: %v", err)
			}
			for _, record := range running {
				if record == nil {
					continue
				}
				if err := jobManager.UpdateStatus(ctx, record.ID, jobs.StatusCancelled, reason); err != nil {
					return nil, http.StatusInternalServerError, fmt.Errorf("failed to cancel running job %s: %v", record.ID, err)
				}
			}
		}
	}

	cfg, cfgErr := builder.ProcessBookConfig(ctx)
	if cfgErr != nil {
		return nil, http.StatusInternalServerError, fmt.Errorf("failed to load config: %v", cfgErr)
	}
	// Apply reset_from from request
	cfg.ResetFrom = req.ResetFrom
	// Apply variant if specified (overrides the default standard variant)
	if req.Variant != "" {
		variant := process_book.PipelineVariant(req.Variant)
		if !variant.IsValid() {
			return nil, http.StatusBadRequest, fmt.Errorf("invalid variant: %s (valid variants: standard, photo-book, text-only, ocr-only)", req.Variant)
		}
		cfg.ApplyVariant(variant)
	}
	job, err = process_book.NewJob(ctx, cfg, bookID)

	if err != nil {
		return nil, http.StatusInternalServerError, fmt.Errorf("failed to create job: %v", err)
	}

	// Submit to scheduler
	if err := scheduler.Submit(ctx, job); err != nil {
		return nil, http.StatusInternalServerError, fmt.Errorf("failed to submit job: %v", err)
	}

	return &StartJobResponse{
		JobID:   job.ID(),
		JobType: jobType,
		BookID:  bookID,
		Status:  "queued",
	}, http.StatusAccepted, nil
}

func (e *StartJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	var resetFrom string
	var variant string
	var force bool
	cmd := &cobra.Command{
		Use:   "start <book_id>",
		Short: "Start job processing for a book",
		Long: `Start the process-book job for a book.

The job processes all pages through OCR, then triggers book-level operations
(metadata extraction, ToC finding, ToC extraction, ToC linking, finalize,
and structure building).

Pipeline variants:
  standard   - Full pipeline (default)
  photo-book - OCR + metadata only (no ToC/structure)
  text-only  - OCR + metadata only (no ToC)
  ocr-only   - OCR only (no LLM processing)

Use --reset-from to re-run a specific operation and all downstream dependencies.
Valid reset operations: metadata, toc_finder, toc_extract, toc_link,
                        toc_finalize, structure, ocr

The command submits a job and returns immediately.
Use 'shelf api jobs get <job-id>' to check progress.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			bookID := args[0]

			client := api.NewClient(getServerURL())
			var resp StartJobResponse
			if err := client.Post(ctx, "/api/jobs/start/"+bookID, StartJobRequest{
				JobType:   process_book.JobType,
				Force:     force,
				ResetFrom: resetFrom,
				Variant:   variant,
			}, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&resetFrom, "reset-from", "", "Reset this operation and downstream deps before starting")
	cmd.Flags().StringVar(&variant, "variant", "", "Pipeline variant (standard, photo-book, text-only, ocr-only)")
	cmd.Flags().BoolVar(&force, "force", false, "Start even if a running job exists for this book")
	return cmd
}
