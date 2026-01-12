package endpoints

import (
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/ingest"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// UploadIngestEndpoint handles POST /api/books/ingest/upload with multipart file upload.
type UploadIngestEndpoint struct{}

var _ api.Endpoint = (*UploadIngestEndpoint)(nil)

func (e *UploadIngestEndpoint) Route() (string, string, http.HandlerFunc) {
	return "POST", "/api/books/ingest/upload", e.handler
}

func (e *UploadIngestEndpoint) RequiresInit() bool { return true }

// handler godoc
//
//	@Summary		Upload and ingest book PDFs
//	@Description	Upload PDF files to ingest as a new book
//	@Tags			books
//	@Accept			mpfd
//	@Produce		json
//	@Param			files		formData	file	true	"PDF files to ingest"
//	@Param			title		formData	string	false	"Book title (derived from filename if not provided)"
//	@Param			author		formData	string	false	"Book author"
//	@Param			auto_process	formData	bool	false	"Automatically start processing after ingest"
//	@Success		202		{object}	IngestResponse
//	@Failure		400		{object}	ErrorResponse
//	@Failure		500		{object}	ErrorResponse
//	@Failure		503		{object}	ErrorResponse
//	@Router			/api/books/ingest/upload [post]
func (e *UploadIngestEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	// Parse multipart form with 500MB max memory
	const maxMemory = 500 << 20 // 500MB
	if err := r.ParseMultipartForm(maxMemory); err != nil {
		writeError(w, http.StatusBadRequest, fmt.Sprintf("failed to parse form: %v", err))
		return
	}
	defer r.MultipartForm.RemoveAll()

	// Get uploaded files
	files := r.MultipartForm.File["files"]
	if len(files) == 0 {
		writeError(w, http.StatusBadRequest, "no files uploaded")
		return
	}

	// Validate all files are PDFs
	for _, fh := range files {
		if !strings.HasSuffix(strings.ToLower(fh.Filename), ".pdf") {
			writeError(w, http.StatusBadRequest, fmt.Sprintf("file %s is not a PDF", fh.Filename))
			return
		}
	}

	// Get optional form fields
	title := r.FormValue("title")
	author := r.FormValue("author")
	autoProcess := r.FormValue("auto_process") == "true"

	// Get services from context
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

	// Create temp directory for uploaded files
	tempDir, err := os.MkdirTemp("", "shelf-upload-*")
	if err != nil {
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create temp dir: %v", err))
		return
	}

	// Save uploaded files to temp directory
	var pdfPaths []string
	for _, fh := range files {
		// Open uploaded file
		src, err := fh.Open()
		if err != nil {
			os.RemoveAll(tempDir)
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to open uploaded file: %v", err))
			return
		}

		// Create destination file
		destPath := filepath.Join(tempDir, fh.Filename)
		dst, err := os.Create(destPath)
		if err != nil {
			src.Close()
			os.RemoveAll(tempDir)
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to create file: %v", err))
			return
		}

		// Copy file contents
		_, err = io.Copy(dst, src)
		src.Close()
		dst.Close()
		if err != nil {
			os.RemoveAll(tempDir)
			writeError(w, http.StatusInternalServerError, fmt.Sprintf("failed to save file: %v", err))
			return
		}

		pdfPaths = append(pdfPaths, destPath)
	}

	// Create and configure the ingest job
	job := ingest.NewJob(ingest.JobConfig{
		PDFPaths: pdfPaths,
		Title:    title,
		Author:   author,
		Logger:   logger,
	})
	job.SetDependencies(client, homeDir)

	// Run ingest synchronously (it's fast - just copies PDFs and creates Book record)
	if _, err := job.Start(r.Context()); err != nil {
		os.RemoveAll(tempDir)
		writeError(w, http.StatusInternalServerError, fmt.Sprintf("ingest failed: %v", err))
		return
	}

	bookID := job.BookID()
	status, _ := job.Status(r.Context())

	// Build response
	resp := IngestResponse{
		JobID:  job.ID(),
		BookID: bookID,
		Title:  status["title"],
		Author: author,
		Status: "completed",
	}

	// Auto-start process-book job if requested
	if autoProcess && bookID != "" {
		if err := scheduler.SubmitByType(r.Context(), "process-book", bookID); err != nil {
			if logger != nil {
				logger.Error("failed to submit process-book job", "error", err, "book_id", bookID)
			}
			// Don't fail the request - ingest succeeded, just note the process didn't start
		} else {
			resp.Status = "processing"
			if logger != nil {
				logger.Info("auto-started process-book job", "book_id", bookID)
			}
		}
	}

	// Clean up temp directory (originals are already copied)
	os.RemoveAll(tempDir)

	writeJSON(w, http.StatusOK, resp)
}

func (e *UploadIngestEndpoint) Command(_ func() string) *cobra.Command {
	// No CLI command for file upload - use the path-based ingest command instead
	return nil
}
