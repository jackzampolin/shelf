package endpoints

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

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
//	@Param			job_type	query		string	false	"Job type (default: process-book)"
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
		jobType = process_book.JobType
	}

	// Get status based on job type
	var resp JobStatusResponse
	resp.BookID = bookID
	resp.JobType = jobType

	switch jobType {
	case process_book.JobType:
		// First try to get live status from a running job (more up-to-date)
		if scheduler := svcctx.SchedulerFrom(r.Context()); scheduler != nil {
			if job := scheduler.GetJobByBookID(bookID); job != nil {
				if provider, ok := job.(jobs.LiveStatusProvider); ok {
					if live := provider.LiveStatus(); live != nil {
						resp.TotalPages = live.TotalPages
						resp.OcrComplete = live.OcrComplete
						resp.BlendComplete = live.BlendComplete
						resp.LabelComplete = live.LabelComplete
						resp.MetadataComplete = live.MetadataComplete
						resp.TocFound = live.TocFound
						resp.TocExtracted = live.TocExtracted
						resp.IsComplete = live.LabelComplete >= live.TotalPages && live.MetadataComplete && live.TocExtracted
						writeJSON(w, http.StatusOK, resp)
						return
					}
				}
			}
		}

		// Fall back to DB query if no active job or live status unavailable
		status, err := process_book.GetStatus(r.Context(), bookID)
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
			if jobType != process_book.JobType {
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
	cmd.Flags().StringVar(&jobType, "job-type", process_book.JobType, "Job type to check")
	return cmd
}
