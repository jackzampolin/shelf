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

type RepairTocEntryRequest struct {
	EntryDocID string `json:"entry_doc_id"`
	Reason     string `json:"reason"`
	Force      bool   `json:"force,omitempty"`
}

type RepairTocEntryResponse struct {
	BookID     string `json:"book_id"`
	TocDocID   string `json:"toc_doc_id"`
	EntryDocID string `json:"entry_doc_id"`
	Title      string `json:"title,omitempty"`
	SortOrder  int    `json:"sort_order"`
	Reason     string `json:"reason"`
	CID        string `json:"cid,omitempty"`
	JobID      string `json:"job_id"`
	Status     string `json:"status"`
}

// RepairTocEntryEndpoint handles POST /api/books/{book_id}/repair-toc-entry.
type RepairTocEntryEndpoint struct{}

func (e *RepairTocEntryEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/repair-toc-entry", e.handler
}

func (e *RepairTocEntryEndpoint) RequiresInit() bool { return true }

func (e *RepairTocEntryEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req RepairTocEntryRequest
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
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create ToC entry repair job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	if _, err := common.ValidateTocEntryRepair(r.Context(), book, req.EntryDocID, req.Reason); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	repair, err := common.RepairTocEntry(r.Context(), book, req.EntryDocID, req.Reason)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to repair ToC entry: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit ToC entry repair job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, RepairTocEntryResponse{
		BookID: bookID, TocDocID: repair.TocDocID,
		EntryDocID: repair.EntryDocID, Title: repair.Title, SortOrder: repair.SortOrder,
		Reason: repair.Reason, CID: repair.CID,
		JobID: job.ID(), Status: "queued",
	})
}

func (e *RepairTocEntryEndpoint) Command(getServerURL func() string) *cobra.Command {
	var entryDocID, reason string
	var force bool
	cmd := &cobra.Command{
		Use:   "repair-toc-entry <book_id>",
		Short: "Retry one unlinked ToC entry without clearing successful links",
		Long: `Reset one unlinked ToC entry's durable retry budget and stale agent
state, then submit a replacement process-book job. Existing successful entry
links are preserved. Finalize and structure are rebuilt because they may have
treated the entry as skipped. Use --force when a job is currently active.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var resp RepairTocEntryResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/repair-toc-entry", RepairTocEntryRequest{
				EntryDocID: entryDocID, Reason: reason, Force: force,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&entryDocID, "entry", "", "TocEntry document ID from detailed job status")
	cmd.Flags().StringVar(&reason, "reason", "", "Source-backed reason for retrying the entry")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job before repair")
	_ = cmd.MarkFlagRequired("entry")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
