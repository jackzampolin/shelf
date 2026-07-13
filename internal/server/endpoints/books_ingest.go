package endpoints

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"

	pdfapi "github.com/pdfcpu/pdfcpu/pkg/api"
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
	Stitch   bool     `json:"stitch,omitempty"`
}

// IngestResponse is the response for a successful ingest job submission.
type IngestResponse struct {
	JobID        string `json:"job_id"`
	BookID       string `json:"book_id,omitempty"`
	Title        string `json:"title"`
	Author       string `json:"author,omitempty"`
	Status       string `json:"status"`
	ProcessJobID string `json:"process_job_id,omitempty"`
}

// BatchIngestResponse is returned by the CLI for --stitch directory ingest.
type BatchIngestResponse struct {
	Jobs    []IngestResponse `json:"jobs"`
	Skipped []SkippedIngest  `json:"skipped,omitempty"`
}

// SkippedIngest reports a PDF group skipped by a batch ingest preflight.
type SkippedIngest struct {
	Name  string   `json:"name"`
	Parts []string `json:"parts"`
	Error string   `json:"error"`
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
		Stitch:   req.Stitch,
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
	var stitch bool
	var stitchPattern string
	cmd := &cobra.Command{
		Use:   "ingest <pdf-files...>",
		Short: "Ingest PDF scans into the library",
		Long: `Ingest one or more PDF files as a book.

For a single multi-part scan, files are sorted by numeric suffix (e.g., book-1.pdf, book-2.pdf).
With --stitch, pass one directory. PDF files are grouped by trailing part number and
submitted as separate ingest jobs, with multi-part groups merged before ingest.
Title is derived from the filename if not provided.

This command submits an ingest job and returns immediately.
Use 'shelf api jobs get <job-id>' to check progress.`,
		Args: cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())

			if stitch {
				if len(args) != 1 {
					return fmt.Errorf("--stitch expects exactly one directory argument")
				}

				dir, err := filepath.Abs(args[0])
				if err != nil {
					return fmt.Errorf("invalid directory %s: %w", args[0], err)
				}

				groups, err := groupedPDFsFromDir(dir, stitchPattern)
				if err != nil {
					return err
				}
				if len(groups) == 0 {
					return fmt.Errorf("no PDF files found in %s", dir)
				}
				if title != "" && len(groups) > 1 {
					return fmt.Errorf("--title can only be used with --stitch when the directory resolves to one book")
				}

				responses := make([]IngestResponse, 0, len(groups))
				skipped := make([]SkippedIngest, 0)
				for _, group := range groups {
					if err := validatePDFParts(group.Parts); err != nil {
						skipped = append(skipped, SkippedIngest{
							Name:  group.Name,
							Parts: group.Parts,
							Error: err.Error(),
						})
						continue
					}

					reqTitle := group.Name
					if title != "" {
						reqTitle = title
					}

					var resp IngestResponse
					if err := client.Post(ctx, "/api/books/ingest", IngestRequest{
						PDFPaths: group.Parts,
						Title:    reqTitle,
						Author:   author,
						Stitch:   len(group.Parts) > 1,
					}, &resp); err != nil {
						// Record the failure and keep going so one bad submit doesn't
						// abort the batch or discard the report of what did/didn't queue.
						skipped = append(skipped, SkippedIngest{
							Name:  group.Name,
							Parts: group.Parts,
							Error: err.Error(),
						})
						continue
					}
					responses = append(responses, resp)
				}

				if len(responses) == 1 && len(skipped) == 0 {
					return api.Output(responses[0])
				}
				if err := api.Output(BatchIngestResponse{Jobs: responses, Skipped: skipped}); err != nil {
					return err
				}
				// Surface a non-zero exit when nothing was ingested, after reporting.
				if len(responses) == 0 {
					return fmt.Errorf("no books ingested: all %d group(s) failed", len(skipped))
				}
				return nil
			}

			// Resolve paths to absolute
			paths := make([]string, len(args))
			for i, arg := range args {
				abs, err := filepath.Abs(arg)
				if err != nil {
					return fmt.Errorf("invalid path %s: %w", arg, err)
				}
				paths[i] = abs
			}

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
	cmd.Flags().BoolVar(&stitch, "stitch", false, "Treat the argument as a directory and group numbered PDF parts into books")
	cmd.Flags().StringVar(&stitchPattern, "stitch-pattern", ingest.DefaultPartPattern.String(), "Regex used by --stitch to identify trailing part numbers")
	return cmd
}

func groupedPDFsFromDir(dir, patternText string) ([]ingest.BookParts, error) {
	info, err := os.Stat(dir)
	if err != nil {
		return nil, fmt.Errorf("invalid directory %s: %w", dir, err)
	}
	if !info.IsDir() {
		return nil, fmt.Errorf("--stitch expects a directory, got %s", dir)
	}

	pattern, err := regexp.Compile(patternText)
	if err != nil {
		return nil, fmt.Errorf("invalid --stitch-pattern: %w", err)
	}

	entries, err := os.ReadDir(dir)
	if err != nil {
		return nil, fmt.Errorf("failed to read directory %s: %w", dir, err)
	}

	paths := make([]string, 0, len(entries))
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if strings.ToLower(filepath.Ext(entry.Name())) != ".pdf" {
			continue
		}
		paths = append(paths, filepath.Join(dir, entry.Name()))
	}

	return ingest.GroupParts(paths, pattern), nil
}

func validatePDFParts(paths []string) error {
	for _, path := range paths {
		f, err := os.Open(path)
		if err != nil {
			return fmt.Errorf("%s: %w", path, err)
		}

		_, pageCountErr := pdfapi.PageCount(f, nil)
		closeErr := f.Close()
		if pageCountErr != nil {
			return fmt.Errorf("%s: %w", path, pageCountErr)
		}
		if closeErr != nil {
			return fmt.Errorf("%s: %w", path, closeErr)
		}
	}
	return nil
}
