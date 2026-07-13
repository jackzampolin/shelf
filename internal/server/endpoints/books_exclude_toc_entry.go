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

type ExcludeTocEntryRequest struct {
	EntryDocID string `json:"entry_doc_id"`
	Reason     string `json:"reason"`
	Linked     bool   `json:"linked,omitempty"`
	Force      bool   `json:"force,omitempty"`
}

type ExcludeTocEntryResponse struct {
	BookID       string `json:"book_id"`
	TocDocID     string `json:"toc_doc_id"`
	EntryDocID   string `json:"entry_doc_id"`
	Title        string `json:"title,omitempty"`
	SortOrder    int    `json:"sort_order"`
	Reason       string `json:"reason"`
	CID          string `json:"cid,omitempty"`
	PendingCount int    `json:"pending_count"`
	JobID        string `json:"job_id"`
	Status       string `json:"status"`
}

type ExcludeTocEntryEndpoint struct{}

func (e *ExcludeTocEntryEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/exclude-toc-entry", e.handler
}

func (e *ExcludeTocEntryEndpoint) RequiresInit() bool { return true }

func (e *ExcludeTocEntryEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req ExcludeTocEntryRequest
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
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create ToC entry exclusion job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	if err := common.ValidateTocEntryExclusion(r.Context(), book, req.EntryDocID, req.Reason, req.Linked); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	exclusion, err := common.ExcludeTocEntry(r.Context(), book, req.EntryDocID, req.Reason, req.Linked)
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to exclude ToC entry: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit ToC entry exclusion job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, ExcludeTocEntryResponse{
		BookID: bookID, TocDocID: exclusion.TocDocID,
		EntryDocID: exclusion.EntryDocID, Title: exclusion.Title, SortOrder: exclusion.SortOrder,
		Reason: exclusion.Reason, CID: exclusion.CID, PendingCount: exclusion.PendingCount,
		JobID: job.ID(), Status: "queued",
	})
}

func (e *ExcludeTocEntryEndpoint) Command(getServerURL func() string) *cobra.Command {
	var entryDocID, reason string
	var force, linked bool
	cmd := &cobra.Command{
		Use:   "exclude-toc-entry <book_id>",
		Short: "Exclude a non-content ToC item absent from the source artifact",
		Long: `Mark one unlinked ToC entry explicitly excluded with a source-backed
reason, preserve successful links, and rebuild downstream stages. This is not a
retry escape hatch: use it only when the source artifact does not contain the
item. Use --force when a job is active.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var resp ExcludeTocEntryResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/exclude-toc-entry", ExcludeTocEntryRequest{
				EntryDocID: entryDocID, Reason: reason, Linked: linked, Force: force,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&entryDocID, "entry", "", "Unlinked TocEntry document ID from detailed job status")
	cmd.Flags().StringVar(&reason, "reason", "", "Source-backed reason the item is absent or non-content")
	cmd.Flags().BoolVar(&linked, "linked", false, "Allow unlinking a verified duplicate or non-content entry")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job before exclusion")
	_ = cmd.MarkFlagRequired("entry")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
