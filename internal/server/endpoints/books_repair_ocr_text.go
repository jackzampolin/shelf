package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

type RepairOCRTextRequest struct {
	Page      int    `json:"page"`
	Text      string `json:"text"`
	Reason    string `json:"reason"`
	ResetFrom string `json:"reset_from,omitempty"`
	Force     bool   `json:"force,omitempty"`
	Variant   string `json:"variant,omitempty"`
}

type RepairOCRTextResponse struct {
	BookID         string `json:"book_id"`
	Page           int    `json:"page"`
	Characters     int    `json:"characters"`
	DeletedResults int    `json:"deleted_results"`
	Provider       string `json:"provider"`
	Reason         string `json:"reason"`
	ResetFrom      string `json:"reset_from"`
	JobID          string `json:"job_id"`
	Status         string `json:"status"`
}

type RepairOCRTextEndpoint struct{}

func (e *RepairOCRTextEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/repair-ocr-text", e.handler
}

func (e *RepairOCRTextEndpoint) RequiresInit() bool { return true }

func (e *RepairOCRTextEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req RepairOCRTextRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if req.Page < 1 {
		writeError(w, http.StatusBadRequest, "page must be positive")
		return
	}
	if strings.TrimSpace(req.Text) == "" {
		writeError(w, http.StatusBadRequest, "verified text is required; describe a source-blank page explicitly")
		return
	}
	if strings.TrimSpace(req.Reason) == "" {
		writeError(w, http.StatusBadRequest, "source verification reason is required")
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
	if req.Page > pageCount {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("page %d is outside valid range 1-%d", req.Page, pageCount))
		return
	}

	var resetPlan []common.ResetOperation
	if req.ResetFrom == "" || req.ResetFrom == "auto" {
		resetPlan = repairInvalidationPlan(cfg, []int{req.Page})
	} else {
		if !common.IsValidResetOperation(req.ResetFrom) || req.ResetFrom == string(common.ResetOcr) {
			writeError(w, http.StatusBadRequest, "reset_from must be auto, metadata, toc_finder, toc_extract, toc_link, toc_finalize, or structure")
			return
		}
		resetPlan = []common.ResetOperation{common.ResetOperation(req.ResetFrom)}
	}

	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}
	job, err := process_book.NewJob(r.Context(), cfg, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create verified OCR repair job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	repair, err := common.RepairOCRTextPage(r.Context(), book, req.Page, req.Text, req.Reason)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to persist verified OCR text: %v", err))
		return
	}
	for _, op := range resetPlan {
		if err := common.ResetFrom(r.Context(), book, book.TocDocID(), op); err != nil {
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to invalidate downstream state from %s: %v", op, err))
			return
		}
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit verified OCR repair job: %v", err))
		return
	}
	resetFrom := "none"
	if len(resetPlan) > 0 {
		resetFrom = string(resetPlan[0])
	}
	writeJSON(w, http.StatusAccepted, RepairOCRTextResponse{
		BookID: bookID, Page: repair.Page, Characters: repair.Characters,
		DeletedResults: repair.DeletedResults, Provider: common.OperatorVerifiedOCRProvider,
		Reason: strings.TrimSpace(req.Reason), ResetFrom: resetFrom, JobID: job.ID(), Status: "queued",
	})
}

func (e *RepairOCRTextEndpoint) Command(getServerURL func() string) *cobra.Command {
	var textFile, reason, resetFrom, variant string
	var page int
	var force bool
	cmd := &cobra.Command{
		Use:   "repair-ocr-text <book_id>",
		Short: "Repair one OCR page with source-verified text",
		Long: `Persist an operator-verified transcription for a pathological page,
including durable provenance and reason, clear quarantine, invalidate the
selected downstream stage, and restart processing. For a blank source page,
the text file must explicitly describe the blank page.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			textBytes, err := os.ReadFile(textFile)
			if err != nil {
				return fmt.Errorf("read verified text file: %w", err)
			}
			var resp RepairOCRTextResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/repair-ocr-text", RepairOCRTextRequest{
				Page: page, Text: string(textBytes), Reason: reason, ResetFrom: resetFrom, Force: force, Variant: variant,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().IntVar(&page, "page", 0, "Page number to repair")
	cmd.Flags().StringVar(&textFile, "text-file", "", "UTF-8 file containing the verified page transcription")
	cmd.Flags().StringVar(&reason, "reason", "", "Source-backed verification reason")
	cmd.Flags().StringVar(&resetFrom, "reset-from", "auto", "Downstream reset stage (auto or an explicit stage)")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job first")
	cmd.Flags().StringVar(&variant, "variant", "", "Pipeline variant (standard, photo-book, text-only, ocr-only)")
	_ = cmd.MarkFlagRequired("page")
	_ = cmd.MarkFlagRequired("text-file")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
