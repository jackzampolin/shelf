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

type ResolveTocEntryRequest struct {
	EntryDocID string `json:"entry_doc_id"`
	PageNum    int    `json:"page_num"`
	Reason     string `json:"reason"`
	Relink     bool   `json:"relink,omitempty"`
	Force      bool   `json:"force,omitempty"`
}

type ResolveTocEntryResponse struct {
	BookID       string `json:"book_id"`
	TocDocID     string `json:"toc_doc_id"`
	EntryDocID   string `json:"entry_doc_id"`
	Title        string `json:"title,omitempty"`
	SortOrder    int    `json:"sort_order"`
	PageNum      int    `json:"page_num"`
	Reason       string `json:"reason"`
	CID          string `json:"cid,omitempty"`
	PendingCount int    `json:"pending_count"`
	JobID        string `json:"job_id"`
	Status       string `json:"status"`
}

// ResolveTocEntryEndpoint handles POST /api/books/{book_id}/resolve-toc-entry.
type ResolveTocEntryEndpoint struct{}

func (e *ResolveTocEntryEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/resolve-toc-entry", e.handler
}

func (e *ResolveTocEntryEndpoint) RequiresInit() bool { return true }

func (e *ResolveTocEntryEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req ResolveTocEntryRequest
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
	if !cfg.EnableTocLink {
		writeError(w, http.StatusBadRequest, "ToC linking is disabled in the active pipeline config")
		return
	}

	job, err := process_book.NewJob(r.Context(), cfg, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create ToC entry resolution job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	if err := common.ValidateTocEntryResolution(r.Context(), book, req.EntryDocID, req.PageNum, req.Reason, req.Relink); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	resolution, err := common.ResolveTocEntry(r.Context(), book, req.EntryDocID, req.PageNum, req.Reason, req.Relink)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("failed to resolve ToC entry: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit ToC entry resolution job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, ResolveTocEntryResponse{
		BookID: bookID, TocDocID: resolution.TocDocID,
		EntryDocID: resolution.EntryDocID, Title: resolution.Title, SortOrder: resolution.SortOrder,
		PageNum: resolution.PageNum, Reason: resolution.Reason, CID: resolution.CID,
		PendingCount: resolution.PendingCount,
		JobID:        job.ID(), Status: "queued",
	})
}

func (e *ResolveTocEntryEndpoint) Command(getServerURL func() string) *cobra.Command {
	var entryDocID, reason string
	var pageNum int
	var force, relink bool
	cmd := &cobra.Command{
		Use:   "resolve-toc-entry <book_id>",
		Short: "Link one ToC entry to an operator-verified scan page",
		Long: `Persist an explicit TocEntry-to-Page link with a source-backed reason,
preserve every successful link, rebuild finalize/structure, and resume processing.
Use this only after inspecting the target page. Use --force when a job is active.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var resp ResolveTocEntryResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/resolve-toc-entry", ResolveTocEntryRequest{
				EntryDocID: entryDocID, PageNum: pageNum, Reason: reason, Relink: relink, Force: force,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&entryDocID, "entry", "", "TocEntry document ID from detailed job status")
	cmd.Flags().IntVar(&pageNum, "page", 0, "Verified 1-indexed scan page")
	cmd.Flags().StringVar(&reason, "reason", "", "Source-backed reason for the explicit page link")
	cmd.Flags().BoolVar(&relink, "relink", false, "Allow replacing an existing page link after source verification")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job before resolution")
	_ = cmd.MarkFlagRequired("entry")
	_ = cmd.MarkFlagRequired("page")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
