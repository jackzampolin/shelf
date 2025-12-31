package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/jobs/process_pages"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// IngestRequest is the request body for ingesting book scans.
type IngestRequest struct {
	PDFPaths []string `json:"pdf_paths"`
	Title    string   `json:"title,omitempty"`
	Author   string   `json:"author,omitempty"`
}

// IngestResponse is the response for a successful ingest job submission.
type IngestResponse struct {
	JobID  string `json:"job_id"`
	Title  string `json:"title"`
	Author string `json:"author,omitempty"`
	Status string `json:"status"`
}

// IngestEndpoint handles POST /api/books/ingest.
type IngestEndpoint struct{}

func (e *IngestEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/books/ingest", e.handler
}

func (e *IngestEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Ingest book scans
//	@Description	Ingest PDF files as a new book and start processing
//	@Tags			books
//	@Accept			json
//	@Produce		json
//	@Param			request	body		IngestRequest	true	"Ingest request"
//	@Success		202		{object}	IngestResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/books/ingest [post]
func (e *IngestEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	var req IngestRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	if len(req.PDFPaths) == 0 {
		writeError(w, http.StatusBadRequest, "pdf_paths is required")
		return
	}

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	homeDir := svcctx.HomeFrom(r.Context())
	if homeDir == nil {
		writeError(w, http.StatusServiceUnavailable, "home directory not initialized")
		return
	}

	scheduler := svcctx.SchedulerFrom(r.Context())
	if scheduler == nil {
		writeError(w, http.StatusServiceUnavailable, "scheduler not initialized")
		return
	}

	logger := svcctx.LoggerFrom(r.Context())

	// Create and configure the ingest job
	job := ingest.NewJob(ingest.JobConfig{
		PDFPaths: req.PDFPaths,
		Title:    req.Title,
		Author:   req.Author,
		Logger:   logger,
	})
	job.SetDependencies(client, homeDir)

	// Submit to scheduler (async)
	if err := scheduler.Submit(r.Context(), job); err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	// Return job ID for status polling
	status, _ := job.Status(r.Context())
	writeJSON(w, http.StatusAccepted, IngestResponse{
		JobID:  job.ID(),
		Title:  status["title"],
		Author: req.Author,
		Status: "queued",
	})
}

func (e *IngestEndpoint) Command(getServerURL func() string) *cobra.Command {
	var title, author string
	cmd := &cobra.Command{
		Use:   "ingest <pdf-files...>",
		Short: "Ingest PDF scans into the library",
		Long: `Ingest one or more PDF files as a book.

For multi-part scans, files are sorted by numeric suffix (e.g., book-1.pdf, book-2.pdf).
Title is derived from the filename if not provided.

This command submits an ingest job and returns immediately.
Use 'shelf api jobs get <job-id>' to check progress.`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			// Resolve paths to absolute
			paths := make([]string, len(args))
			for i, arg := range args {
				abs, err := filepath.Abs(arg)
				if err != nil {
					return fmt.Errorf("invalid path %s: %w", arg, err)
				}
				paths[i] = abs
			}

			client := api.NewClient(getServerURL())
			var resp IngestResponse
			if err := client.Post(ctx, "/api/books/ingest", IngestRequest{
				PDFPaths: paths,
				Title:    title,
				Author:   author,
			}, &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
	cmd.Flags().StringVar(&title, "title", "", "Book title (derived from filename if not provided)")
	cmd.Flags().StringVar(&author, "author", "", "Book author")
	return cmd
}

// ListBooksResponse is the response for listing books.
type ListBooksResponse struct {
	Books []Book `json:"books"`
}

// Book represents a book record.
type Book struct {
	ID        string `json:"id"`
	Title     string `json:"title"`
	Author    string `json:"author,omitempty"`
	PageCount int    `json:"page_count"`
	Status    string `json:"status"`
	CreatedAt string `json:"created_at"`
}

// ListBooksEndpoint handles GET /api/books.
type ListBooksEndpoint struct{}

func (e *ListBooksEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books", e.handler
}

func (e *ListBooksEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		List books
//	@Description	List all books in the library
//	@Tags			books
//	@Produce		json
//	@Success		200	{object}	ListBooksResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/books [get]
func (e *ListBooksEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	resp, err := client.Query(r.Context(), `{
		Book {
			_docID
			title
			author
			page_count
			status
			created_at
		}
	}`)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	var books []Book
	if data, ok := resp.Data["Book"].([]any); ok {
		for _, item := range data {
			if m, ok := item.(map[string]any); ok {
				book := Book{
					ID:     getString(m, "_docID"),
					Title:  getString(m, "title"),
					Author: getString(m, "author"),
					Status: getString(m, "status"),
				}
				if pc, ok := m["page_count"].(float64); ok {
					book.PageCount = int(pc)
				}
				if ca, ok := m["created_at"].(string); ok {
					book.CreatedAt = ca
				}
				books = append(books, book)
			}
		}
	}

	writeJSON(w, http.StatusOK, ListBooksResponse{Books: books})
}

func (e *ListBooksEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List all books",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp ListBooksResponse
			if err := client.Get(ctx, "/api/books", &resp); err != nil {
				return err
			}

			return api.Output(resp)
		},
	}
}

// GetBookEndpoint handles GET /api/books/{id}.
type GetBookEndpoint struct{}

func (e *GetBookEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}", e.handler
}

func (e *GetBookEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Get book by ID
//	@Description	Get detailed information about a book
//	@Tags			books
//	@Produce		json
//	@Param			id	path		string	true	"Book ID"
//	@Success		200	{object}	Book
//	@Failure		400	{object}	ErrorResponse
//	@Failure		404	{object}	ErrorResponse
//	@Failure		500	{object}	ErrorResponse
//	@Failure		503	{object}	ErrorResponse
//	@Router			/api/books/{id} [get]
func (e *GetBookEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	id := r.PathValue("id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "book id is required")
		return
	}

	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	query := fmt.Sprintf(`{
		Book(docID: %q) {
			_docID
			title
			author
			page_count
			status
			created_at
		}
	}`, id)

	resp, err := client.Query(r.Context(), query)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}

	if errMsg := resp.Error(); errMsg != "" {
		writeError(w, http.StatusInternalServerError, errMsg)
		return
	}

	data, ok := resp.Data["Book"].([]any)
	if !ok || len(data) == 0 {
		writeError(w, http.StatusNotFound, "book not found")
		return
	}

	m, ok := data[0].(map[string]any)
	if !ok {
		writeError(w, http.StatusInternalServerError, "unexpected response format")
		return
	}

	book := Book{
		ID:     getString(m, "_docID"),
		Title:  getString(m, "title"),
		Author: getString(m, "author"),
		Status: getString(m, "status"),
	}
	if pc, ok := m["page_count"].(float64); ok {
		book.PageCount = int(pc)
	}
	if ca, ok := m["created_at"].(string); ok {
		book.CreatedAt = ca
	}

	writeJSON(w, http.StatusOK, book)
}

func (e *GetBookEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "get <id>",
		Short: "Get a book by ID",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var book Book
			if err := client.Get(ctx, "/api/books/"+args[0], &book); err != nil {
				return err
			}
			return api.Output(book)
		},
	}
}

// getString safely extracts a string from a map.
func getString(m map[string]any, key string) string {
	if v, ok := m[key].(string); ok {
		return v
	}
	return ""
}

// RerunTocResponse is the response for rerunning ToC.
type RerunTocResponse struct {
	JobID   string `json:"job_id"`
	Message string `json:"message"`
}

// RerunTocEndpoint handles POST /api/books/{book_id}/rerun-toc.
type RerunTocEndpoint struct {
	ProcessPagesConfig process_pages.Config
}

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
					"toc_found":        false,
					"finder_started":   false,
					"finder_complete":  false,
					"finder_failed":    false,
					"finder_retries":   0,
					"extract_started":  false,
					"extract_complete": false,
					"extract_failed":   false,
					"extract_retries":  0,
					"start_page":       nil,
					"end_page":         nil,
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

	// Create a new process-pages job
	job, err := process_pages.NewJob(r.Context(), e.ProcessPagesConfig, bookID)
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
