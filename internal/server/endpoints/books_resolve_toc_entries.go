package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

type ResolveTocEntriesRequest struct {
	Resolutions []ResolveTocEntryRequest `json:"resolutions"`
	Force       bool                     `json:"force,omitempty"`
}

type ResolveTocEntriesResponse struct {
	BookID       string                          `json:"book_id"`
	TocDocID     string                          `json:"toc_doc_id"`
	Resolutions  []ResolveTocEntriesItemResponse `json:"resolutions"`
	PendingCount int                             `json:"pending_count"`
	JobID        string                          `json:"job_id"`
	Status       string                          `json:"status"`
}

type ResolveTocEntriesItemResponse struct {
	EntryDocID string `json:"entry_doc_id"`
	Title      string `json:"title,omitempty"`
	SortOrder  int    `json:"sort_order"`
	PageNum    int    `json:"page_num"`
	Reason     string `json:"reason"`
	CID        string `json:"cid,omitempty"`
}

// ResolveTocEntriesEndpoint handles one source-backed repair cohort with one
// active-job cancellation and one replacement process-book submission.
type ResolveTocEntriesEndpoint struct{}

func (e *ResolveTocEntriesEndpoint) Route() (string, string, http.HandlerFunc) {
	return http.MethodPost, "/api/books/{book_id}/resolve-toc-entries", e.handler
}

func (e *ResolveTocEntriesEndpoint) RequiresInit() bool { return true }

func (e *ResolveTocEntriesEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}
	var req ResolveTocEntriesRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}
	if len(req.Resolutions) == 0 {
		writeError(w, http.StatusBadRequest, "at least one ToC entry resolution is required")
		return
	}
	if len(req.Resolutions) > 100 {
		writeError(w, http.StatusBadRequest, "ToC entry resolution batch exceeds limit of 100")
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
	specs := make([]common.TocEntryResolutionSpec, 0, len(req.Resolutions))
	seen := make(map[string]struct{}, len(req.Resolutions))
	for _, resolution := range req.Resolutions {
		if _, duplicate := seen[resolution.EntryDocID]; duplicate {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("duplicate ToC entry %q in resolution batch", resolution.EntryDocID))
			return
		}
		seen[resolution.EntryDocID] = struct{}{}
		if err := common.ValidateTocEntryResolution(r.Context(), book, resolution.EntryDocID, resolution.PageNum, resolution.Reason, resolution.Relink); err != nil {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("invalid ToC entry %s: %v", resolution.EntryDocID, err))
			return
		}
		specs = append(specs, common.TocEntryResolutionSpec{
			EntryDocID:  resolution.EntryDocID,
			PageNum:     resolution.PageNum,
			Title:       resolution.Title,
			Reason:      resolution.Reason,
			AllowRelink: resolution.Relink,
		})
	}
	if httpStatus, err := prepareBookJobStart(r.Context(), scheduler, bookID, process_book.JobType, req.Force); err != nil {
		writeError(w, httpStatus, err.Error())
		return
	}

	resolved, pendingCount, err := common.ResolveTocEntries(r.Context(), book, specs)
	if err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("failed to resolve ToC entries: %v", err))
		return
	}
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to submit ToC entry resolution job: %v", err))
		return
	}

	items := make([]ResolveTocEntriesItemResponse, 0, len(resolved))
	for _, resolution := range resolved {
		items = append(items, ResolveTocEntriesItemResponse{
			EntryDocID: resolution.EntryDocID, Title: resolution.Title, SortOrder: resolution.SortOrder,
			PageNum: resolution.PageNum, Reason: resolution.Reason, CID: resolution.CID,
		})
	}
	writeJSON(w, http.StatusAccepted, ResolveTocEntriesResponse{
		BookID: bookID, TocDocID: resolved[0].TocDocID,
		Resolutions: items, PendingCount: pendingCount,
		JobID: job.ID(), Status: "queued",
	})
}

func (e *ResolveTocEntriesEndpoint) Command(getServerURL func() string) *cobra.Command {
	var file string
	var force bool
	cmd := &cobra.Command{
		Use:   "resolve-toc-entries <book_id>",
		Short: "Apply a JSON cohort of source-verified ToC entry links",
		Long: `Validate every entry/page decision before changing state, then apply the
whole cohort with one active-job cancellation and one replacement process-book
job. The JSON file must contain an array of resolve-toc-entry request objects.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			data, err := os.ReadFile(file)
			if err != nil {
				return fmt.Errorf("read resolution file: %w", err)
			}
			var resolutions []ResolveTocEntryRequest
			if err := json.Unmarshal(data, &resolutions); err != nil {
				return fmt.Errorf("decode resolution file: %w", err)
			}
			var resp ResolveTocEntriesResponse
			if err := api.NewClient(getServerURL()).Post(cmd.Context(), "/api/books/"+args[0]+"/resolve-toc-entries", ResolveTocEntriesRequest{
				Resolutions: resolutions,
				Force:       force,
			}, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&file, "file", "", "JSON array of source-verified entry/page resolutions")
	cmd.Flags().BoolVar(&force, "force", false, "Cancel one active process-book job before applying the cohort")
	_ = cmd.MarkFlagRequired("file")
	return cmd
}
