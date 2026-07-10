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

type RepairTocRangeRequest struct {
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"`
	Force     bool   `json:"force,omitempty"`
}

type RepairTocRangeResponse struct {
	BookID    string `json:"book_id"`
	TocDocID  string `json:"toc_doc_id"`
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"`
	CID       string `json:"cid,omitempty"`
	JobID     string `json:"job_id"`
	Status    string `json:"status"`
}

// RepairTocRangeEndpoint handles POST /api/books/{book_id}/repair-toc-range.
type RepairTocRangeEndpoint struct{}

func (e *RepairTocRangeEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/repair-toc-range", e.handler
}

func (e *RepairTocRangeEndpoint) RequiresInit() bool { return true }

func (e *RepairTocRangeEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req RepairTocRangeRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
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
	if !cfg.EnableTocExtract {
		writeError(w, http.StatusBadRequest, "ToC extraction is disabled in the active pipeline config")
		return
	}

	job, err := process_book.NewJob(r.Context(), cfg, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create ToC range repair job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	if err := common.ValidateTocRangeRepair(r.Context(), book, req.StartPage, req.EndPage, req.Reason); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	repair, err := common.RepairTocRange(r.Context(), book, req.StartPage, req.EndPage, req.Reason)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to repair ToC range: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit ToC range repair job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, RepairTocRangeResponse{
		BookID: bookID, TocDocID: repair.TocDocID,
		StartPage: repair.StartPage, EndPage: repair.EndPage,
		Reason: repair.Reason, CID: repair.CID,
		JobID: job.ID(), Status: "queued",
	})
}

func (e *RepairTocRangeEndpoint) Command(getServerURL func() string) *cobra.Command {
	var startPage, endPage int
	var reason string
	var force bool
	cmd := &cobra.Command{
		Use:   "repair-toc-range <book_id>",
		Short: "Override a verified ToC page range and restart extraction",
		Long: `Use a human- or agent-verified OCR page range when automatic ToC discovery
failed or selected the wrong pages. Shelf validates every selected page, records
the override reason, clears extraction and downstream artifacts, and submits a
replacement process-book job. Use --force when a job is currently active.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var resp RepairTocRangeResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/repair-toc-range", RepairTocRangeRequest{
				StartPage: startPage, EndPage: endPage, Reason: reason, Force: force,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().IntVar(&startPage, "start", 0, "First physical ToC page")
	cmd.Flags().IntVar(&endPage, "end", 0, "Last physical ToC page")
	cmd.Flags().StringVar(&reason, "reason", "", "Source-backed reason for the override")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job before repair")
	_ = cmd.MarkFlagRequired("start")
	_ = cmd.MarkFlagRequired("end")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
