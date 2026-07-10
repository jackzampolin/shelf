package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

type QuarantineOCRRequest struct {
	Pages   []int  `json:"pages"`
	Reason  string `json:"reason"`
	Force   bool   `json:"force,omitempty"`
	Variant string `json:"variant,omitempty"`
}

type QuarantineOCRResponse struct {
	BookID         string `json:"book_id"`
	Pages          []int  `json:"pages"`
	Reason         string `json:"reason"`
	DeletedResults int    `json:"deleted_results"`
	JobID          string `json:"job_id"`
	Status         string `json:"status"`
}

// QuarantineOCREndpoint records explicit terminal exceptions for pages that
// cannot produce faithful OCR, then restarts downstream book processing.
type QuarantineOCREndpoint struct{}

func (e *QuarantineOCREndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/quarantine-ocr", e.handler
}

func (e *QuarantineOCREndpoint) RequiresInit() bool { return true }

func (e *QuarantineOCREndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req QuarantineOCRRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	req.Reason = strings.TrimSpace(req.Reason)
	if len(req.Pages) == 0 || req.Reason == "" {
		writeError(w, http.StatusBadRequest, "at least one page and a reason are required")
		return
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	configStore := svcctx.ConfigStoreFrom(r.Context())
	if scheduler == nil || configStore == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler and config store must be initialized")
		return
	}
	cfg, err := jobcfg.NewBuilder(configStore).ProcessBookConfig(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to load config: %v", err))
		return
	}
	if req.Variant != "" {
		variant := process_book.PipelineVariant(req.Variant)
		if !variant.IsValid() {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid variant: %s", req.Variant))
			return
		}
		cfg.ApplyVariant(variant)
	}
	pageCount, err := repairBookPageCount(r.Context(), bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to read book: %v", err))
		return
	}
	if pageCount == 0 {
		writeError(w, http.StatusNotFound, "book not found or has no pages")
		return
	}
	for _, pageNum := range req.Pages {
		if pageNum < 1 || pageNum > pageCount {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("page %d is outside valid range 1-%d", pageNum, pageCount))
			return
		}
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	job, err := process_book.NewJob(r.Context(), cfg, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create quarantine job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	repair, err := common.RepairOCRPages(r.Context(), book, req.Pages, cfg.OcrProviders)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to clear quarantined OCR pages: %v", err))
		return
	}
	pages, err := common.QuarantineOCRPages(r.Context(), book, repair.Pages, req.Reason)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to quarantine OCR pages: %v", err))
		return
	}
	if err := resetRepairDownstream(r.Context(), book, cfg, pages); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to invalidate downstream state: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit quarantine job: %v", err))
		return
	}
	writeJSON(w, http.StatusAccepted, QuarantineOCRResponse{
		BookID:         bookID,
		Pages:          pages,
		Reason:         req.Reason,
		DeletedResults: repair.DeletedResults,
		JobID:          job.ID(),
		Status:         "queued",
	})
}

func (e *QuarantineOCREndpoint) Command(getServerURL func() string) *cobra.Command {
	var pageSpec, reason, variant string
	var force bool
	cmd := &cobra.Command{
		Use:   "quarantine-ocr <book_id>",
		Short: "Quarantine pathological OCR pages and restart processing",
		Long: `Record selected pages as explicit terminal OCR exceptions and restart the
book from affected downstream stages. Quarantined pages remain distinguishable
from successful OCR and can be re-enabled later with books repair-ocr.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			pages, err := parsePageSpec(pageSpec)
			if err != nil {
				return err
			}
			var resp QuarantineOCRResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/quarantine-ocr", QuarantineOCRRequest{
				Pages: pages, Reason: reason, Force: force, Variant: variant,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&pageSpec, "pages", "", "Pages to quarantine (comma-separated numbers and ranges)")
	cmd.Flags().StringVar(&reason, "reason", "", "Evidence-backed reason for quarantine")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job first")
	cmd.Flags().StringVar(&variant, "variant", "", "Pipeline variant (standard, photo-book, text-only, ocr-only)")
	_ = cmd.MarkFlagRequired("pages")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
