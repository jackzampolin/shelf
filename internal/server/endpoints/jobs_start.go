package endpoints

import (
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

	jobType := req.JobType
	if jobType == "" {
		jobType = process_book.JobType
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}

	// Get config store and create builder to read configs at request time
	configStore := svcctx.ConfigStoreFrom(r.Context())
	if configStore == nil {
		writeError(w, http.StatusServiceUnavailable, "config store not initialized")
		return
	}
	builder := jobcfg.NewBuilder(configStore)

	// Create job - only process_book is supported
	var job jobs.Job
	var err error

	if jobType != process_book.JobType {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("unknown job type: %s (only 'process-book' is supported)", jobType))
		return
	}

	cfg, cfgErr := builder.ProcessBookConfig(r.Context())
	if cfgErr != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to load config: %v", cfgErr))
		return
	}
	// Apply reset_from from request
	cfg.ResetFrom = req.ResetFrom
	// Apply variant if specified (overrides the default standard variant)
	if req.Variant != "" {
		variant := process_book.PipelineVariant(req.Variant)
		if !variant.IsValid() {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid variant: %s (valid variants: standard, photo-book, text-only, ocr-only)", req.Variant))
			return
		}
		cfg.ApplyVariant(variant)
	}
	job, err = process_book.NewJob(r.Context(), cfg, bookID)

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
	var resetFrom string
	var variant string
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
	return cmd
}
