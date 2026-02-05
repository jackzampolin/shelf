// Package ingest handles book scan ingestion from PDF files.
package ingest

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/pdfcpu/pdfcpu/pkg/api"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
)

// Request contains the parameters for ingesting book scans.
type Request struct {
	PDFPaths []string     // PDF file paths (will be sorted by numeric suffix)
	Title    string       // Book title (optional, derived from filename if empty)
	Author   string       // Book author (optional)
	Logger   *slog.Logger // Optional logger for progress updates
}

// Result contains the result of a successful ingest operation.
type Result struct {
	BookID    string
	Title     string
	Author    string
	PageCount int
}

// Ingest extracts pages from PDFs and creates a Book record in DefraDB.
func Ingest(ctx context.Context, client *defra.Client, homeDir *home.Dir, req Request) (*Result, error) {
	log := req.Logger
	if log == nil {
		log = slog.Default()
	}

	if len(req.PDFPaths) == 0 {
		return nil, fmt.Errorf("no PDF paths provided")
	}

	// Validate all PDF paths exist
	for _, p := range req.PDFPaths {
		if _, err := os.Stat(p); err != nil {
			return nil, fmt.Errorf("PDF not found: %s", p)
		}
	}

	// Sort PDFs by numeric suffix (e.g., book-1.pdf, book-2.pdf)
	sortedPaths := sortPDFsByNumber(req.PDFPaths)
	log.Info("starting ingest", "pdfs", len(sortedPaths), "title", req.Title)

	// Derive title from first PDF filename if not provided
	title := req.Title
	if title == "" {
		title = deriveTitle(sortedPaths[0])
	}

	// Generate book ID
	bookID := uuid.New().String()

	// Create output directory
	if err := homeDir.EnsureSourceImagesDir(bookID); err != nil {
		return nil, fmt.Errorf("failed to create output directory: %w", err)
	}
	outDir := homeDir.SourceImagesDir(bookID)

	// Extract images from all PDFs
	pageCount := 0
	for i, pdfPath := range sortedPaths {
		log.Debug("extracting PDF", "file", filepath.Base(pdfPath), "part", i+1, "of", len(sortedPaths))
		count, err := extractImages(pdfPath, outDir, pageCount)
		if err != nil {
			// Clean up on failure
			os.RemoveAll(outDir)
			return nil, fmt.Errorf("failed to extract images from %s: %w", pdfPath, err)
		}
		log.Debug("extracted pages", "count", count, "total", pageCount+count)
		pageCount += count
	}

	if pageCount == 0 {
		os.RemoveAll(outDir)
		return nil, fmt.Errorf("no images extracted from PDFs")
	}

	log.Debug("creating book record", "title", title, "pages", pageCount)

	// Create Book record in DefraDB
	input := map[string]any{
		"title":      title,
		"page_count": pageCount,
		"status":     "ingested",
		"created_at": time.Now().UTC().Format(time.RFC3339),
	}
	if req.Author != "" {
		input["author"] = req.Author
	}

	docID, err := client.Create(ctx, "Book", input)
	if err != nil {
		// Clean up on failure
		os.RemoveAll(outDir)
		return nil, fmt.Errorf("failed to create Book record: %w", err)
	}

	// Rename directory from UUID to docID
	newDir := homeDir.SourceImagesDir(docID)
	if err := os.Rename(outDir, newDir); err != nil {
		return nil, fmt.Errorf("failed to rename directory: %w", err)
	}

	log.Info("ingest complete", "book_id", docID, "pages", pageCount)

	return &Result{
		BookID:    docID,
		Title:     title,
		Author:    req.Author,
		PageCount: pageCount,
	}, nil
}

// extractImages renders all pages from a PDF to the output directory using pdftoppm.
// Returns the number of pages extracted.
// startPage is the offset for page numbering (for multi-part PDFs).
func extractImages(pdfPath, outDir string, pageOffset int) (int, error) {
	// Get page count
	f, err := os.Open(pdfPath)
	if err != nil {
		return 0, fmt.Errorf("failed to open PDF: %w", err)
	}
	pageCount, err := api.PageCount(f, nil)
	f.Close()
	if err != nil {
		return 0, fmt.Errorf("failed to get page count: %w", err)
	}

	// Process pages concurrently
	maxWorkers := runtime.NumCPU()

	type result struct {
		pageNum int
		err     error
	}

	results := make(chan result, pageCount)
	sem := make(chan struct{}, maxWorkers)

	for page := 1; page <= pageCount; page++ {
		sem <- struct{}{} // acquire
		go func(pageInPDF int) {
			defer func() { <-sem }() // release

			outputPageNum := pageOffset + pageInPDF
			err := renderPage(pdfPath, outDir, pageInPDF, outputPageNum)
			results <- result{pageNum: pageInPDF, err: err}
		}(page)
	}

	// Collect results
	successCount := 0
	for i := 0; i < pageCount; i++ {
		r := <-results
		if r.err != nil {
			return 0, fmt.Errorf("failed to render page %d: %w", r.pageNum, r.err)
		}
		successCount++
	}

	return successCount, nil
}

// renderPage renders a single page from a PDF using pdftoppm (poppler-utils).
func renderPage(pdfPath, outDir string, pageInPDF, outputPageNum int) error {
	// Create temp directory for output
	tmpDir, err := os.MkdirTemp("", "shelf-page-*")
	if err != nil {
		return fmt.Errorf("failed to create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	// Output prefix for pdftoppm
	outputPrefix := filepath.Join(tmpDir, "page")

	// Run pdftoppm to render the page
	// -png: output PNG format
	// -f N: first page to render
	// -l N: last page to render
	// -r 300: resolution in DPI
	// -singlefile: don't add page number suffix
	pageStr := fmt.Sprintf("%d", pageInPDF)
	cmd := exec.Command("pdftoppm",
		"-png",
		"-f", pageStr,
		"-l", pageStr,
		"-r", "300",
		"-singlefile",
		pdfPath,
		outputPrefix,
	)

	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("pdftoppm failed: %w (output: %s)", err, string(output))
	}

	// pdftoppm with -singlefile creates: <prefix>.png
	srcPath := outputPrefix + ".png"
	if _, err := os.Stat(srcPath); err != nil {
		return fmt.Errorf("pdftoppm did not create expected output: %w", err)
	}

	// Read the rendered image
	data, err := os.ReadFile(srcPath)
	if err != nil {
		return fmt.Errorf("failed to read rendered image: %w", err)
	}

	// Write to destination with sequential naming
	dstPath := filepath.Join(outDir, fmt.Sprintf("page_%04d.png", outputPageNum))
	if err := os.WriteFile(dstPath, data, 0o644); err != nil {
		return fmt.Errorf("failed to write page image: %w", err)
	}

	return nil
}

// sortPDFsByNumber sorts PDF paths by their numeric suffix.
// e.g., ["book-2.pdf", "book-1.pdf", "book-10.pdf"] -> ["book-1.pdf", "book-2.pdf", "book-10.pdf"]
func sortPDFsByNumber(paths []string) []string {
	sorted := make([]string, len(paths))
	copy(sorted, paths)

	re := regexp.MustCompile(`-(\d+)\.pdf$`)

	sort.Slice(sorted, func(i, j int) bool {
		mi := re.FindStringSubmatch(sorted[i])
		mj := re.FindStringSubmatch(sorted[j])

		// If both have numbers, sort numerically
		if len(mi) > 1 && len(mj) > 1 {
			ni, _ := strconv.Atoi(mi[1])
			nj, _ := strconv.Atoi(mj[1])
			return ni < nj
		}

		// Files without numbers come first
		if len(mi) > 1 {
			return false
		}
		if len(mj) > 1 {
			return true
		}

		// Both without numbers: alphabetical
		return sorted[i] < sorted[j]
	})

	return sorted
}

// deriveTitle extracts a title from a PDF filename.
// e.g., "crusade-europe.pdf" -> "crusade-europe"
// e.g., "my-book-1.pdf" -> "my-book"
func deriveTitle(pdfPath string) string {
	base := filepath.Base(pdfPath)
	name := strings.TrimSuffix(base, filepath.Ext(base))

	// Remove numeric suffix like "-1", "-2", etc.
	re := regexp.MustCompile(`-\d+$`)
	name = re.ReplaceAllString(name, "")

	return name
}
