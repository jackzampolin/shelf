package endpoints

import (
	"fmt"
	"net/http"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobcfg"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// RerunTocResponse is the response for rerunning ToC.
type RerunTocResponse struct {
	JobID   string `json:"job_id"`
	Message string `json:"message"`
}

// RerunTocEndpoint handles POST /api/books/{book_id}/rerun-toc.
// Config is read from DefraDB at request time.
type RerunTocEndpoint struct{}

func (e *RerunTocEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/books/{book_id}/rerun-toc", e.handler
}

func (e *RerunTocEndpoint) RequiresInit() bool { return true }

// BlendCompleteThreshold is the minimum number of pages with blend_complete
// required before allowing ToC rerun.
const BlendCompleteThreshold = 50

// handler godoc
//
//	@Summary		Rerun ToC finder and extractor
//	@Description	Reset ToC state and rerun the ToC finder and extractor agents
//	@Tags			books
//	@Produce		json
//	@Param			book_id	path		string	true	"Book ID"
//	@Success		202		{object}	RerunTocResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		404		{object}	ErrorResponse
//	@Failure		412		{object}	ErrorResponse	"Not enough pages have blend complete"
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/books/{book_id}/rerun-toc [post]
func (e *RerunTocEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	bookID := r.PathValue("book_id")
	if bookID == "" {
		writeError(w, http.StatusBadRequest, "book_id is required")
		return
	}

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}

	// Get config store for reading settings
	configStore := svcctx.ConfigStoreFrom(r.Context())
	if configStore == nil {
		writeError(w, http.StatusServiceUnavailable, "config store not initialized")
		return
	}

	// Check if book exists and get page count
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			_docID
			page_count
			toc {
				_docID
			}
		}
	}`, bookID)

	bookResp, err := client.Execute(r.Context(), bookQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	books, ok := bookResp.Data["Book"].([]any)
	if !ok || len(books) == 0 {
		writeError(w, http.StatusNotFound, "book not found")
		return
	}

	book, _ := books[0].(map[string]any)
	pageCount := 0
	if pc, ok := book["page_count"].(float64); ok {
		pageCount = int(pc)
	}

	var tocDocID string
	if toc, ok := book["toc"].(map[string]any); ok {
		if docID, ok := toc["_docID"].(string); ok {
			tocDocID = docID
		}
	}

	// Count pages with blend_complete
	pageQuery := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, blend_complete: {_eq: true}}) {
			_docID
		}
	}`, bookID)

	pageResp, err := client.Execute(r.Context(), pageQuery, nil)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	blendCompleteCount := 0
	if pages, ok := pageResp.Data["Page"].([]any); ok {
		blendCompleteCount = len(pages)
	}

	// Check threshold - use min of threshold and page count for small books
	threshold := BlendCompleteThreshold
	if pageCount < threshold {
		threshold = pageCount
	}

	if blendCompleteCount < threshold {
		writeError(w, http.StatusPreconditionFailed,
			fmt.Sprintf("not enough pages have blend complete: %d/%d (need %d)",
				blendCompleteCount, pageCount, threshold))
		return
	}

	// Reset ToC state if ToC record exists
	if tocDocID != "" {
		sink := svcctx.DefraSinkFrom(r.Context())
		if sink != nil {
			// Reset finder and extractor state
			_, err := sink.SendSync(r.Context(), defra.WriteOp{
				Collection: "ToC",
				DocID:      tocDocID,
				Document: map[string]any{
					"toc_found":         false,
					"finder_started":    false,
					"finder_complete":   false,
					"finder_failed":     false,
					"finder_retries":    0,
					"extract_started":   false,
					"extract_complete":  false,
					"extract_failed":    false,
					"extract_retries":   0,
					"start_page":        nil,
					"end_page":          nil,
					"structure_summary": nil,
				},
				Op: defra.OpUpdate,
			})
			if err != nil {
				writeError(w, http.StatusInternalServerError,
					fmt.Sprintf("failed to reset ToC state: %v", err))
				return
			}

			// Delete existing ToC entries
			entriesQuery := fmt.Sprintf(`{
				TocEntry(filter: {toc_id: {_eq: "%s"}}) {
					_docID
				}
			}`, tocDocID)
			entriesResp, err := client.Execute(r.Context(), entriesQuery, nil)
			if err == nil {
				if entries, ok := entriesResp.Data["TocEntry"].([]any); ok {
					for _, entry := range entries {
						if entryMap, ok := entry.(map[string]any); ok {
							if entryDocID, ok := entryMap["_docID"].(string); ok {
								sink.Send(defra.WriteOp{
									Collection: "TocEntry",
									DocID:      entryDocID,
									Op:         defra.OpDelete,
								})
							}
						}
					}
				}
			}
		}
	}

	// Build config from DefraDB and create job
	builder := jobcfg.NewBuilder(configStore)
	cfg, err := builder.ProcessBookConfig(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError,
			fmt.Sprintf("failed to load config: %v", err))
		return
	}

	job, err := process_book.NewJob(r.Context(), cfg, bookID)
	if err != nil {
		writeError(w, http.StatusInternalServerError,
			fmt.Sprintf("failed to create job: %v", err))
		return
	}

	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError,
			fmt.Sprintf("failed to submit job: %v", err))
		return
	}

	writeJSON(w, http.StatusAccepted, RerunTocResponse{
		JobID:   job.ID(),
		Message: fmt.Sprintf("ToC rerun started for book %s", bookID),
	})
}

func (e *RerunTocEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "rerun-toc <book-id>",
		Short: "Rerun ToC finder and extractor for a book",
		Long: `Reset ToC state and rerun the ToC finder and extractor agents.

Requires at least 50 pages (or all pages for smaller books) to have
completed blend processing before the ToC agents can run.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp RerunTocResponse
			if err := client.Post(ctx, "/api/books/"+args[0]+"/rerun-toc", nil, &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}
