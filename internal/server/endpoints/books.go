package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"path/filepath"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/ingest"
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

			fmt.Printf("Ingest job submitted: %s\n", resp.JobID)
			fmt.Printf("  Title:  %s\n", resp.Title)
			if resp.Author != "" {
				fmt.Printf("  Author: %s\n", resp.Author)
			}
			fmt.Printf("  Status: %s\n", resp.Status)
			fmt.Println("\nCheck progress with: shelf api jobs get", resp.JobID)
			return nil
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

			if len(resp.Books) == 0 {
				fmt.Println("No books found")
				return nil
			}

			for _, book := range resp.Books {
				fmt.Printf("%s  %s  %d pages  %s\n", book.ID[:8], book.Title, book.PageCount, book.Status)
			}
			return nil
		},
	}
}

// GetBookEndpoint handles GET /api/books/{id}.
type GetBookEndpoint struct{}

func (e *GetBookEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/books/{id}", e.handler
}

func (e *GetBookEndpoint) RequiresInit() bool { return true }

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
			fmt.Printf("ID:        %s\n", book.ID)
			fmt.Printf("Title:     %s\n", book.Title)
			if book.Author != "" {
				fmt.Printf("Author:    %s\n", book.Author)
			}
			fmt.Printf("Pages:     %d\n", book.PageCount)
			fmt.Printf("Status:    %s\n", book.Status)
			fmt.Printf("Created:   %s\n", book.CreatedAt)
			return nil
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
