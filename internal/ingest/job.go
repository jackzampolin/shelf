package ingest

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/pdfcpu/pdfcpu/pkg/api"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
)

const (
	JobType         = "ingest"
	TaskExtractPage = "extract-page"
)

// PageExtractRequest is the data for a single page extraction work unit.
type PageExtractRequest struct {
	PDFPath   string // Source PDF file
	PageNum   int    // Page number within the PDF (1-indexed)
	OutputNum int    // Output page number (for sequential naming across PDFs)
	OutputDir string // Directory to write the extracted page
}

// PageExtractResult is returned from a successful page extraction.
type PageExtractResult struct {
	OutputPath string // Path to the extracted image
	PageNum    int    // Output page number
}

// Job implements jobs.Job for ingesting book scans.
// It copies PDFs to the originals directory and creates a Book record.
// Page extraction is handled later by the page_processing stage.
type Job struct {
	mu sync.Mutex

	// Configuration
	pdfPaths []string
	title    string
	author   string
	bookID   string // Generated UUID, later replaced with DefraDB docID
	logger   *slog.Logger

	// Dependencies (set via SetDependencies)
	defraClient *defra.Client
	homeDir     *home.Dir

	// State
	recordID    string   // DefraDB job record ID
	totalPages  int      // Discovered from PDFs
	copiedPDFs  []string // Paths to copied PDFs in originals/
	done        bool
	finalBookID string // DefraDB Book docID after completion
}

// JobConfig configures a new ingest job.
type JobConfig struct {
	PDFPaths []string
	Title    string
	Author   string
	Logger   *slog.Logger
}

// NewJob creates a new ingest job.
func NewJob(cfg JobConfig) *Job {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	// Sort PDFs by numeric suffix
	sortedPaths := sortPDFsByNumber(cfg.PDFPaths)

	// Derive title from first PDF if not provided
	title := cfg.Title
	if title == "" && len(sortedPaths) > 0 {
		title = deriveTitle(sortedPaths[0])
	}

	return &Job{
		pdfPaths: sortedPaths,
		title:    title,
		author:   cfg.Author,
		bookID:   uuid.New().String(),
		logger:   logger.With("job_type", JobType),
	}
}

// SetDependencies sets the DefraDB client and home directory.
// Must be called before submitting the job to the scheduler.
func (j *Job) SetDependencies(client *defra.Client, homeDir *home.Dir) {
	j.defraClient = client
	j.homeDir = homeDir
}

// ID returns the DefraDB record ID for this job.
func (j *Job) ID() string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.recordID
}

// SetRecordID sets the DefraDB record ID.
func (j *Job) SetRecordID(id string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.recordID = id
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return JobType
}

// Start copies PDFs to originals/ directory and creates a Book record.
// No work units are returned - page extraction happens in page_processing stage.
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Validate PDFs exist
	for _, p := range j.pdfPaths {
		if _, err := os.Stat(p); err != nil {
			return nil, fmt.Errorf("PDF not found: %s", p)
		}
	}

	// Create originals directory
	if err := j.homeDir.EnsureOriginalsDir(j.bookID); err != nil {
		return nil, fmt.Errorf("failed to create originals directory: %w", err)
	}
	originalsDir := j.homeDir.OriginalsDir(j.bookID)

	j.logger.Info("starting ingest job",
		"pdfs", len(j.pdfPaths),
		"title", j.title,
		"originals_dir", originalsDir,
	)

	// Copy PDFs and count pages
	totalPages := 0
	var copiedPDFs []string

	for _, pdfPath := range j.pdfPaths {
		// Get page count
		f, err := os.Open(pdfPath)
		if err != nil {
			return nil, fmt.Errorf("failed to open PDF %s: %w", pdfPath, err)
		}
		pageCount, err := api.PageCount(f, nil)
		f.Close()
		if err != nil {
			return nil, fmt.Errorf("failed to get page count for %s: %w", pdfPath, err)
		}

		totalPages += pageCount

		// Copy PDF to originals directory
		destPath := filepath.Join(originalsDir, filepath.Base(pdfPath))
		if err := copyFile(pdfPath, destPath); err != nil {
			return nil, fmt.Errorf("failed to copy PDF %s: %w", pdfPath, err)
		}
		copiedPDFs = append(copiedPDFs, destPath)

		j.logger.Info("copied PDF",
			"file", filepath.Base(pdfPath),
			"pages", pageCount,
		)
	}

	j.totalPages = totalPages
	j.copiedPDFs = copiedPDFs

	// Create Book record in DefraDB immediately
	input := map[string]any{
		"title":      j.title,
		"page_count": totalPages,
		"status":     "ingested",
		"created_at": time.Now().UTC().Format(time.RFC3339),
	}
	if j.author != "" {
		input["author"] = j.author
	}

	docID, err := j.defraClient.Create(ctx, "Book", input)
	if err != nil {
		os.RemoveAll(j.homeDir.SourceImagesDir(j.bookID))
		return nil, fmt.Errorf("failed to create Book record: %w", err)
	}

	// Rename directory from UUID to docID
	oldDir := j.homeDir.SourceImagesDir(j.bookID)
	newDir := j.homeDir.SourceImagesDir(docID)
	if err := os.Rename(oldDir, newDir); err != nil {
		return nil, fmt.Errorf("failed to rename directory: %w", err)
	}

	// Update copied PDF paths to reflect new directory
	newOriginalsDir := j.homeDir.OriginalsDir(docID)
	for i, p := range j.copiedPDFs {
		j.copiedPDFs[i] = filepath.Join(newOriginalsDir, filepath.Base(p))
	}

	j.finalBookID = docID
	j.done = true

	j.logger.Info("ingest complete",
		"book_id", docID,
		"total_pages", totalPages,
		"pdfs", len(copiedPDFs),
	)

	// No work units - ingest is complete
	return nil, nil
}

// OnComplete is called when a work unit finishes.
// For ingest jobs, this is a no-op since Start() completes synchronously.
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	// No work units generated by ingest - this shouldn't be called
	return nil, nil
}

// copyFile copies a file from src to dst.
func copyFile(src, dst string) error {
	srcFile, err := os.Open(src)
	if err != nil {
		return err
	}
	defer srcFile.Close()

	dstFile, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer dstFile.Close()

	_, err = io.Copy(dstFile, srcFile)
	return err
}

// Done returns true when the job has completed.
func (j *Job) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.done
}

// Status returns the current status of the job.
func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	status := map[string]string{
		"title":       j.title,
		"total_pages": fmt.Sprintf("%d", j.totalPages),
		"pdfs_copied": fmt.Sprintf("%d", len(j.copiedPDFs)),
		"done":        fmt.Sprintf("%v", j.done),
	}

	if j.author != "" {
		status["author"] = j.author
	}
	if j.finalBookID != "" {
		status["book_id"] = j.finalBookID
	}

	return status, nil
}

// Progress returns per-provider work unit progress.
// Ingest jobs complete synchronously, so this returns 100% when done.
func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()

	completed := 0
	if j.done {
		completed = len(j.copiedPDFs)
	}

	return map[string]jobs.ProviderProgress{
		"copy": {
			TotalExpected: len(j.pdfPaths),
			Completed:     completed,
			Failed:        0,
		},
	}
}

// BookID returns the DefraDB Book document ID after successful completion.
// Returns empty string if job is not yet complete.
func (j *Job) BookID() string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.finalBookID
}

// MetricsFor returns nil for ingest jobs (CPU-only work, no API costs).
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return nil
}
