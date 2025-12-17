// Package ingest handles book scan ingestion from PDF files.
package ingest

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/pdfcpu/pdfcpu/pkg/api"
	"github.com/pdfcpu/pdfcpu/pkg/pdfcpu/model"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
)

// Request contains the parameters for ingesting book scans.
type Request struct {
	PDFPaths []string    // PDF file paths (will be sorted by numeric suffix)
	Title    string      // Book title (optional, derived from filename if empty)
	Author   string      // Book author (optional)
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
		log.Info("extracting PDF", "file", filepath.Base(pdfPath), "part", i+1, "of", len(sortedPaths))
		count, err := extractImages(pdfPath, outDir, pageCount)
		if err != nil {
			// Clean up on failure
			os.RemoveAll(outDir)
			return nil, fmt.Errorf("failed to extract images from %s: %w", pdfPath, err)
		}
		log.Info("extracted pages", "count", count, "total", pageCount+count)
		pageCount += count
	}

	if pageCount == 0 {
		os.RemoveAll(outDir)
		return nil, fmt.Errorf("no images extracted from PDFs")
	}

	log.Info("creating book record", "title", title, "pages", pageCount)

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

// decryptPDF removes encryption/permissions from a PDF.
// Returns the path to the decrypted PDF (may be same as input if not encrypted).
func decryptPDF(pdfPath string, conf *model.Configuration) (string, error) {
	// Create temp file for decrypted PDF
	tmpFile, err := os.CreateTemp("", "shelf-decrypt-*.pdf")
	if err != nil {
		return "", fmt.Errorf("failed to create temp file: %w", err)
	}
	tmpPath := tmpFile.Name()
	tmpFile.Close()

	// Try to decrypt the PDF (empty password for PDFs with no user password)
	if err := api.DecryptFile(pdfPath, tmpPath, conf); err != nil {
		os.Remove(tmpPath)
		// If decrypt fails (not encrypted or other issue), use original
		// Common error: "this file is not encrypted" - that's fine, use original
		return pdfPath, nil
	}

	return tmpPath, nil
}

// extractImages extracts all images from a PDF to the output directory.
// Returns the number of images extracted.
// startPage is the offset for page numbering (for multi-part PDFs).
func extractImages(pdfPath, outDir string, startPage int) (int, error) {
	conf := model.NewDefaultConfiguration()
	conf.ValidationMode = model.ValidationRelaxed

	// Try to decrypt PDF to remove permission restrictions
	// This works on PDFs with restrictive permission bits (even without encryption password)
	workingPath, err := decryptPDF(pdfPath, conf)
	if err != nil {
		return 0, fmt.Errorf("failed to prepare PDF: %w", err)
	}
	if workingPath != pdfPath {
		defer os.Remove(workingPath)
	}

	// Get page count
	f, err := os.Open(workingPath)
	if err != nil {
		return 0, fmt.Errorf("failed to open PDF: %w", err)
	}
	pageCount, err := api.PageCount(f, nil)
	f.Close()
	if err != nil {
		return 0, fmt.Errorf("failed to get page count: %w", err)
	}

	// Process in chunks concurrently
	const chunkSize = 50
	maxWorkers := runtime.NumCPU()

	type result struct {
		chunkStart int
		count      int
		err        error
	}

	chunks := make([][]int, 0)
	for start := 1; start <= pageCount; start += chunkSize {
		end := start + chunkSize - 1
		if end > pageCount {
			end = pageCount
		}
		chunks = append(chunks, []int{start, end})
	}

	results := make(chan result, len(chunks))
	sem := make(chan struct{}, maxWorkers)

	for _, chunk := range chunks {
		sem <- struct{}{} // acquire
		go func(start, end int) {
			defer func() { <-sem }() // release

			count, err := extractChunk(workingPath, outDir, start, end, startPage, conf)
			results <- result{chunkStart: start, count: count, err: err}
		}(chunk[0], chunk[1])
	}

	// Collect results
	totalCount := 0
	for range chunks {
		r := <-results
		if r.err != nil {
			return 0, fmt.Errorf("failed to extract pages %d+: %w", r.chunkStart, r.err)
		}
		totalCount += r.count
	}

	return totalCount, nil
}

// extractChunk extracts a range of pages from a PDF.
func extractChunk(pdfPath, outDir string, startPage, endPage, pageOffset int, conf *model.Configuration) (int, error) {
	// Create a temp directory for this chunk
	tmpDir, err := os.MkdirTemp("", "shelf-chunk-*")
	if err != nil {
		return 0, fmt.Errorf("failed to create temp dir: %w", err)
	}
	defer os.RemoveAll(tmpDir)

	// Build page selection
	pages := make([]string, 0)
	for p := startPage; p <= endPage; p++ {
		pages = append(pages, strconv.Itoa(p))
	}

	// Extract images for this page range
	if err := api.ExtractImagesFile(pdfPath, tmpDir, pages, conf); err != nil {
		return 0, fmt.Errorf("pdfcpu extract failed: %w", err)
	}

	// Read extracted files
	entries, err := os.ReadDir(tmpDir)
	if err != nil {
		return 0, fmt.Errorf("failed to read temp dir: %w", err)
	}

	// Sort entries to maintain page order
	sortExtractedFiles(entries)

	count := 0
	for i, entry := range entries {
		if entry.IsDir() {
			continue
		}

		// Read source file
		srcPath := filepath.Join(tmpDir, entry.Name())
		data, err := os.ReadFile(srcPath)
		if err != nil {
			return 0, fmt.Errorf("failed to read extracted image: %w", err)
		}

		// Write to destination with sequential naming
		// pageOffset is cumulative from previous PDFs, startPage is within this PDF
		pageNum := pageOffset + startPage + i
		dstPath := filepath.Join(outDir, fmt.Sprintf("page_%04d.png", pageNum))
		if err := os.WriteFile(dstPath, data, 0o644); err != nil {
			return 0, fmt.Errorf("failed to write page image: %w", err)
		}

		count++
	}

	return count, nil
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

// sortExtractedFiles sorts directory entries by the page number in their filename.
// pdfcpu names files like "book_1_Im1.png", "book_2_Im2.png"
func sortExtractedFiles(entries []os.DirEntry) {
	re := regexp.MustCompile(`_(\d+)_`)

	sort.Slice(entries, func(i, j int) bool {
		mi := re.FindStringSubmatch(entries[i].Name())
		mj := re.FindStringSubmatch(entries[j].Name())

		if len(mi) > 1 && len(mj) > 1 {
			ni, _ := strconv.Atoi(mi[1])
			nj, _ := strconv.Atoi(mj[1])
			return ni < nj
		}

		return entries[i].Name() < entries[j].Name()
	})
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
