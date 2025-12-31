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
