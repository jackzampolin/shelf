package ingest

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/google/uuid"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"

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
// It discovers pages across all input PDFs, then farms out
// individual page extractions to CPU workers.
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
	recordID       string // DefraDB job record ID
	outputDir      string
	totalPages     int
	completedPages int
	failedPages    int
	done           bool
	finalBookID    string // DefraDB Book docID after completion
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

// Start initializes the job and returns work units for each page.
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Validate PDFs exist
	for _, p := range j.pdfPaths {
		if _, err := os.Stat(p); err != nil {
			return nil, fmt.Errorf("PDF not found: %s", p)
		}
	}

	// Create output directory
	if err := j.homeDir.EnsureSourceImagesDir(j.bookID); err != nil {
		return nil, fmt.Errorf("failed to create output directory: %w", err)
	}
	j.outputDir = j.homeDir.SourceImagesDir(j.bookID)

	j.logger.Info("starting ingest job",
		"pdfs", len(j.pdfPaths),
		"title", j.title,
		"output_dir", j.outputDir,
	)

	// Discovery: count pages in all PDFs
	conf := model.NewDefaultConfiguration()
	conf.ValidationMode = model.ValidationRelaxed

	var units []jobs.WorkUnit
	outputNum := 1

	for _, pdfPath := range j.pdfPaths {
		// Try to decrypt to remove permission restrictions
		workingPath, err := decryptPDF(pdfPath, conf)
		if err != nil {
			return nil, fmt.Errorf("failed to prepare PDF %s: %w", pdfPath, err)
		}

		// Get page count
		f, err := os.Open(workingPath)
		if err != nil {
			if workingPath != pdfPath {
				os.Remove(workingPath)
			}
			return nil, fmt.Errorf("failed to open PDF %s: %w", pdfPath, err)
		}
		pageCount, err := api.PageCount(f, nil)
		f.Close()
		if err != nil {
			if workingPath != pdfPath {
				os.Remove(workingPath)
			}
			return nil, fmt.Errorf("failed to get page count for %s: %w", pdfPath, err)
		}

		// Clean up temp file if we created one
		if workingPath != pdfPath {
			os.Remove(workingPath)
		}

		j.logger.Info("discovered PDF",
			"file", filepath.Base(pdfPath),
			"pages", pageCount,
		)

		// Create work unit for each page
		for pageNum := 1; pageNum <= pageCount; pageNum++ {
			units = append(units, jobs.WorkUnit{
				ID:   fmt.Sprintf("%s-page-%d", j.bookID, outputNum),
				Type: jobs.WorkUnitTypeCPU,
				CPURequest: &jobs.CPUWorkRequest{
					Task: TaskExtractPage,
					Data: PageExtractRequest{
						PDFPath:   pdfPath,
						PageNum:   pageNum,
						OutputNum: outputNum,
						OutputDir: j.outputDir,
					},
				},
			})
			outputNum++
		}
	}

	j.totalPages = len(units)
	j.logger.Info("created work units", "total_pages", j.totalPages)

	return units, nil
}

// OnComplete is called when a work unit finishes.
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	if result.Success {
		j.completedPages++
		j.logger.Debug("page extracted",
			"completed", j.completedPages,
			"total", j.totalPages,
		)
	} else {
		j.failedPages++
		j.logger.Warn("page extraction failed",
			"unit_id", result.WorkUnitID,
			"error", result.Error,
		)
	}

	// Check if all pages are done
	if j.completedPages+j.failedPages >= j.totalPages {
		if err := j.finalize(ctx); err != nil {
			j.logger.Error("failed to finalize job", "error", err)
			return nil, err
		}
		j.done = true
	}

	return nil, nil
}

// finalize creates the Book record in DefraDB after all pages are extracted.
// Must be called with lock held.
func (j *Job) finalize(ctx context.Context) error {
	if j.failedPages > 0 {
		// Clean up on failure
		os.RemoveAll(j.outputDir)
		return fmt.Errorf("ingest failed: %d pages failed to extract", j.failedPages)
	}

	j.logger.Info("finalizing ingest",
		"title", j.title,
		"pages", j.completedPages,
	)

	// Create Book record in DefraDB
	input := map[string]any{
		"title":      j.title,
		"page_count": j.completedPages,
		"status":     "ingested",
		"created_at": time.Now().UTC().Format(time.RFC3339),
	}
	if j.author != "" {
		input["author"] = j.author
	}

	docID, err := j.defraClient.Create(ctx, "Book", input)
	if err != nil {
		os.RemoveAll(j.outputDir)
		return fmt.Errorf("failed to create Book record: %w", err)
	}

	// Rename directory from UUID to docID
	newDir := j.homeDir.SourceImagesDir(docID)
	if err := os.Rename(j.outputDir, newDir); err != nil {
		return fmt.Errorf("failed to rename directory: %w", err)
	}

	j.finalBookID = docID
	j.logger.Info("ingest complete",
		"book_id", docID,
		"pages", j.completedPages,
	)

	return nil
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
		"title":           j.title,
		"total_pages":     fmt.Sprintf("%d", j.totalPages),
		"completed_pages": fmt.Sprintf("%d", j.completedPages),
		"failed_pages":    fmt.Sprintf("%d", j.failedPages),
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
func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()

	return map[string]jobs.ProviderProgress{
		"cpu": {
			TotalExpected: j.totalPages,
			Completed:     j.completedPages,
			Failed:        j.failedPages,
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
