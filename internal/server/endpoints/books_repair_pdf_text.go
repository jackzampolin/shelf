package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

type RepairPDFTextRequest struct {
	Pages    []int  `json:"pages"`
	MinChars int    `json:"min_chars,omitempty"`
	Force    bool   `json:"force,omitempty"`
	Variant  string `json:"variant,omitempty"`
}

type RepairPDFTextResponse struct {
	BookID         string `json:"book_id"`
	Pages          []int  `json:"pages"`
	Characters     int    `json:"characters"`
	DeletedResults int    `json:"deleted_results"`
	Provider       string `json:"provider"`
	JobID          string `json:"job_id"`
	Status         string `json:"status"`
}

type RepairPDFTextEndpoint struct{}

func (e *RepairPDFTextEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/repair-pdf-text", e.handler
}

func (e *RepairPDFTextEndpoint) RequiresInit() bool { return true }

func (e *RepairPDFTextEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req RepairPDFTextRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if len(req.Pages) == 0 {
		writeError(w, http.StatusBadRequest, "at least one page is required")
		return
	}
	if req.MinChars == 0 {
		req.MinChars = 50
	}
	if req.MinChars < 1 {
		writeError(w, http.StatusBadRequest, "min_chars must be positive")
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
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create PDF text repair job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	repair, err := common.RepairPDFTextPages(r.Context(), book, req.Pages, req.MinChars)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to repair pages from PDF text: %v", err))
		return
	}
	if err := resetRepairDownstream(r.Context(), book, cfg, repair.Pages); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to invalidate downstream state: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit PDF text repair job: %v", err))
		return
	}
	writeJSON(w, http.StatusAccepted, RepairPDFTextResponse{
		BookID:         bookID,
		Pages:          repair.Pages,
		Characters:     repair.Characters,
		DeletedResults: repair.DeletedResults,
		Provider:       common.PDFTextProvider,
		JobID:          job.ID(),
		Status:         "queued",
	})
}

func (e *RepairPDFTextEndpoint) Command(getServerURL func() string) *cobra.Command {
	var pageSpec, variant string
	var minChars int
	var force bool
	cmd := &cobra.Command{
		Use:   "repair-pdf-text <book_id>",
		Short: "Repair selected OCR pages from embedded PDF text",
		Long: `Extract selected pages with pdftotext, persist the real embedded text with
pdf-text provenance, clear any page quarantine, invalidate affected downstream
stages, and restart processing. This command rejects empty or tiny text layers.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			pages, err := parsePageSpec(pageSpec)
			if err != nil {
				return err
			}
			var resp RepairPDFTextResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/repair-pdf-text", RepairPDFTextRequest{
				Pages: pages, MinChars: minChars, Force: force, Variant: variant,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&pageSpec, "pages", "", "Pages to repair (comma-separated numbers and ranges)")
	cmd.Flags().IntVar(&minChars, "min-chars", 50, "Minimum embedded characters required per page")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job first")
	cmd.Flags().StringVar(&variant, "variant", "", "Pipeline variant (standard, photo-book, text-only, ocr-only)")
	_ = cmd.MarkFlagRequired("pages")
	return cmd
}
