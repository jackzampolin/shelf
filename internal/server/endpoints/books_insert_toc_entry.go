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

type InsertTocEntryRequest struct {
	Title           string `json:"title"`
	PageNum         int    `json:"page_num"`
	Level           int    `json:"level"`
	LevelName       string `json:"level_name"`
	AfterEntryDocID string `json:"after_entry_doc_id"`
	Reason          string `json:"reason"`
	Force           bool   `json:"force,omitempty"`
}

type InsertTocEntryResponse struct {
	BookID          string `json:"book_id"`
	TocDocID        string `json:"toc_doc_id"`
	EntryDocID      string `json:"entry_doc_id"`
	Title           string `json:"title"`
	SortOrder       int    `json:"sort_order"`
	PageNum         int    `json:"page_num"`
	Level           int    `json:"level"`
	LevelName       string `json:"level_name"`
	AfterEntryDocID string `json:"after_entry_doc_id"`
	Reason          string `json:"reason"`
	CID             string `json:"cid,omitempty"`
	JobID           string `json:"job_id"`
	Status          string `json:"status"`
}

// InsertTocEntryEndpoint handles POST /api/books/{book_id}/insert-toc-entry.
type InsertTocEntryEndpoint struct{}

func (e *InsertTocEntryEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/insert-toc-entry", e.handler
}

func (e *InsertTocEntryEndpoint) RequiresInit() bool { return true }

func (e *InsertTocEntryEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req InsertTocEntryRequest
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
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create ToC entry insertion job: %v", err))
		return
	}
	jobContext, ok := job.(common.JobContext)
	if !ok {
		writeError(w, http.StatusInternalServerError, "process-book job does not expose book state")
		return
	}
	book := jobContext.GetBook()
	spec := common.TocEntryInsertionSpec{
		Title: req.Title, PageNum: req.PageNum, Level: req.Level, LevelName: req.LevelName,
		AfterEntryDocID: req.AfterEntryDocID, Reason: req.Reason,
	}
	if err := common.ValidateTocEntryInsertion(r.Context(), book, spec); err != nil {
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	insertion, err := common.InsertTocEntry(r.Context(), book, spec)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("failed to insert ToC entry: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit ToC entry insertion job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, InsertTocEntryResponse{
		BookID: bookID, TocDocID: insertion.TocDocID, EntryDocID: insertion.EntryDocID,
		Title: insertion.Title, SortOrder: insertion.SortOrder, PageNum: insertion.PageNum,
		Level: insertion.Level, LevelName: insertion.LevelName, AfterEntryDocID: insertion.AfterEntry,
		Reason: insertion.Reason, CID: insertion.CID, JobID: job.ID(), Status: "queued",
	})
}

func (e *InsertTocEntryEndpoint) Command(getServerURL func() string) *cobra.Command {
	var title, levelName, afterEntryDocID, reason string
	var pageNum, level int
	var force bool
	cmd := &cobra.Command{
		Use:   "insert-toc-entry <book_id>",
		Short: "Insert one source-verified heading omitted by ToC extraction",
		Long: `Create and directly link a missing TocEntry after an explicit source-order
anchor, preserve every successful link, rebuild finalize/structure, and resume
processing. Replaying the same insertion is idempotent. Use --force when a job
is active.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			var resp InsertTocEntryResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/insert-toc-entry", InsertTocEntryRequest{
				Title: title, PageNum: pageNum, Level: level, LevelName: levelName,
				AfterEntryDocID: afterEntryDocID, Reason: reason, Force: force,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&title, "title", "", "Source-verified missing heading")
	cmd.Flags().IntVar(&pageNum, "page", 0, "Verified 1-indexed scan page")
	cmd.Flags().IntVar(&level, "level", 3, "Hierarchy level")
	cmd.Flags().StringVar(&levelName, "level-name", "section", "Hierarchy label")
	cmd.Flags().StringVar(&afterEntryDocID, "after", "", "Existing linked TocEntry immediately preceding the missing heading")
	cmd.Flags().StringVar(&reason, "reason", "", "Source-backed insertion reason")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel an active process-book job before insertion")
	_ = cmd.MarkFlagRequired("title")
	_ = cmd.MarkFlagRequired("page")
	_ = cmd.MarkFlagRequired("after")
	_ = cmd.MarkFlagRequired("reason")
	return cmd
}
