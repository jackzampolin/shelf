package endpoints

import (
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// RetryJobRequest is the request body for retrying a failed job.
type RetryJobRequest struct {
	ResetFrom string `json:"reset_from,omitempty"` // Optional; inferred from failed work unit when empty
	Force     bool   `json:"force,omitempty"`      // Optional; cancels an active replacement for this book
	Variant   string `json:"variant,omitempty"`    // Optional process-book pipeline variant
}

// RetryJobResponse is the response for retrying a failed job.
type RetryJobResponse struct {
	PreviousJobID string `json:"previous_job_id"`
	JobID         string `json:"job_id"`
	JobType       string `json:"job_type"`
	BookID        string `json:"book_id"`
	Status        string `json:"status"`
	ResetFrom     string `json:"reset_from"`
}

// RetryJobEndpoint handles POST /api/jobs/retry/{id}.
type RetryJobEndpoint struct{}

func (e *RetryJobEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/jobs/retry/{id}", e.handler
}

func (e *RetryJobEndpoint) RequiresInit() bool { return true }

func (e *RetryJobEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "job id is required")
		return
	}

	var req RetryJobRequest
	if r.Body != nil && r.ContentLength > 0 {
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			writeError(w, http.StatusBadRequest, "invalid request body")
			return
		}
	}

	jm := svcctx.JobManagerFrom(r.Context())
	if jm == nil {
		writeError(w, http.StatusServiceUnavailable, "job manager not initialized")
		return
	}

	record, err := jm.Get(r.Context(), id)
	if err != nil {
		if errors.Is(err, jobs.ErrNotFound) {
			writeError(w, http.StatusNotFound, err.Error())
			return
		}
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if record.Status != jobs.StatusFailed {
		writeError(w, http.StatusConflict, fmt.Sprintf("only failed jobs can be retried; job %s is %s", id, record.Status))
		return
	}
	if record.JobType != process_book.JobType {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("retry supports only %q jobs, got %q", process_book.JobType, record.JobType))
		return
	}

	bookID := jobRecordBookID(record)
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "failed job record has no book_id")
		return
	}

	resetFrom := req.ResetFrom
	if resetFrom == "" {
		resetFrom = inferResetFromJobError(record.Error)
	}
	if resetFrom == "" && !retryWithoutResetAllowed(record.Error) {
		writeError(w, http.StatusBadRequest, "reset_from is required because the failed stage could not be inferred")
		return
	}
	if resetFrom != "" && !common.IsValidResetOperation(resetFrom) {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid reset_from %q", resetFrom))
		return
	}

	startResp, status, err := startJobForBook(r.Context(), bookID, StartJobRequest{
		JobType:   process_book.JobType,
		Force:     req.Force,
		ResetFrom: resetFrom,
		Variant:   req.Variant,
	})
	if err != nil {
		writeError(w, status, err.Error())
		return
	}

	writeJSON(w, status, RetryJobResponse{
		PreviousJobID: id,
		JobID:         startResp.JobID,
		JobType:       startResp.JobType,
		BookID:        startResp.BookID,
		Status:        startResp.Status,
		ResetFrom:     resetFrom,
	})
}

func retryWithoutResetAllowed(errMsg string) bool {
	msg := strings.ToLower(errMsg)
	return strings.Contains(msg, "resume failed to recreate job") ||
		strings.Contains(msg, "failed to load page states") ||
		strings.Contains(msg, "failed to load book")
}

func (e *RetryJobEndpoint) Command(getServerURL func() string) *cobra.Command {
	var resetFrom string
	var force bool
	var variant string
	cmd := &cobra.Command{
		Use:   "retry <id>",
		Short: "Retry a failed job",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp RetryJobResponse
			if err := client.Post(ctx, "/api/jobs/retry/"+args[0], RetryJobRequest{
				ResetFrom: resetFrom,
				Force:     force,
				Variant:   variant,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&resetFrom, "reset-from", "", "Reset this operation and downstream deps before retrying; inferred when omitted")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel any active replacement job for the same book")
	cmd.Flags().StringVar(&variant, "variant", "", "Pipeline variant (standard, photo-book, text-only, ocr-only)")
	return cmd
}

func jobRecordBookID(record *jobs.Record) string {
	if record == nil {
		return ""
	}
	if record.BookID != "" {
		return record.BookID
	}
	if record.Metadata != nil {
		if bookID, ok := record.Metadata["book_id"].(string); ok {
			return bookID
		}
	}
	return ""
}

func inferResetFromJobError(errMsg string) string {
	errMsg = strings.ToLower(errMsg)
	switch {
	case strings.Contains(errMsg, "(metadata)") || strings.Contains(errMsg, "metadata"):
		return string(common.ResetMetadata)
	case strings.Contains(errMsg, "(toc_finder)") || strings.Contains(errMsg, "toc finder"):
		return string(common.ResetTocFinder)
	case strings.Contains(errMsg, "(toc_extract)") || strings.Contains(errMsg, "toc extract") || strings.Contains(errMsg, "toc extraction"):
		return string(common.ResetTocExtract)
	case strings.Contains(errMsg, "(extract)") || strings.Contains(errMsg, "failed to extract page") || strings.Contains(errMsg, "page extraction"):
		return string(common.ResetOcr)
	case strings.Contains(errMsg, "(link_toc)") || strings.Contains(errMsg, "link_toc") || strings.Contains(errMsg, "toc link"):
		return string(common.ResetTocLink)
	case strings.Contains(errMsg, "finalize"):
		return string(common.ResetTocFinalize)
	case strings.Contains(errMsg, "structure"):
		return string(common.ResetStructure)
	case strings.Contains(errMsg, "(ocr)") || strings.Contains(errMsg, "ocr"):
		return string(common.ResetOcr)
	default:
		return ""
	}
}
