package process_pages

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/pdfcpu/pdfcpu/pkg/api"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/home"
	"github.com/jackzampolin/shelf/internal/jobs"
	pjob "github.com/jackzampolin/shelf/internal/jobs/process_pages/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "process-pages"

// Config configures the process pages job.
type Config struct {
	OcrProviders     []string
	BlendProvider    string
	LabelProvider    string
	MetadataProvider string
	TocProvider      string
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if len(c.OcrProviders) == 0 {
		return fmt.Errorf("at least one OCR provider is required")
	}
	if c.BlendProvider == "" {
		return fmt.Errorf("blend provider is required")
	}
	if c.LabelProvider == "" {
		return fmt.Errorf("label provider is required")
	}
	if c.MetadataProvider == "" {
		return fmt.Errorf("metadata provider is required")
	}
	if c.TocProvider == "" {
		return fmt.Errorf("toc provider is required")
	}
	return nil
}

// Status represents the status of page processing for a book.
type Status struct {
	TotalPages       int  `json:"total_pages"`
	OcrComplete      int  `json:"ocr_complete"`
	BlendComplete    int  `json:"blend_complete"`
	LabelComplete    int  `json:"label_complete"`
	MetadataComplete bool `json:"metadata_complete"`
	TocFound         bool `json:"toc_found"`
	TocExtracted     bool `json:"toc_extracted"`
}

// IsComplete returns whether processing is complete for this book.
func (st *Status) IsComplete() bool {
	allPagesComplete := st.LabelComplete >= st.TotalPages
	return allPagesComplete && st.MetadataComplete && st.TocExtracted
}

// GetStatus queries DefraDB for the current processing status of a book.
func GetStatus(ctx context.Context, bookID string) (*Status, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	return GetStatusWithClient(ctx, defraClient, bookID)
}

// GetStatusWithClient queries DefraDB for status using the provided client.
func GetStatusWithClient(ctx context.Context, client *defra.Client, bookID string) (*Status, error) {
	// Query book for total pages and metadata status
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
			metadata_complete
		}
	}`, bookID)

	bookResp, err := client.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	status := &Status{}

	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				status.TotalPages = int(pc)
			}
			if mc, ok := book["metadata_complete"].(bool); ok {
				status.MetadataComplete = mc
			}
		}
	}

	// Query page completion counts
	pageQuery := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			ocr_complete
			blend_complete
			label_complete
		}
	}`, bookID)

	pageResp, err := client.Execute(ctx, pageQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query pages: %w", err)
	}

	if pages, ok := pageResp.Data["Page"].([]any); ok {
		for _, p := range pages {
			page, ok := p.(map[string]any)
			if !ok {
				continue
			}
			if ocrComplete, ok := page["ocr_complete"].(bool); ok && ocrComplete {
				status.OcrComplete++
			}
			if blendComplete, ok := page["blend_complete"].(bool); ok && blendComplete {
				status.BlendComplete++
			}
			if labelComplete, ok := page["label_complete"].(bool); ok && labelComplete {
				status.LabelComplete++
			}
		}
	}

	// Query ToC status
	tocQuery := fmt.Sprintf(`{
		ToC(filter: {book_id: {_eq: "%s"}}) {
			toc_found
			extract_complete
		}
	}`, bookID)

	tocResp, err := client.Execute(ctx, tocQuery, nil)
	if err == nil {
		if tocs, ok := tocResp.Data["ToC"].([]any); ok && len(tocs) > 0 {
			if toc, ok := tocs[0].(map[string]any); ok {
				if found, ok := toc["toc_found"].(bool); ok {
					status.TocFound = found
				}
				if extracted, ok := toc["extract_complete"].(bool); ok {
					status.TocExtracted = extracted
				}
			}
		}
	}

	return status, nil
}

// NewJob creates a new process pages job for the given book.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil, fmt.Errorf("defra client not in context")
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Get book info
	bookQuery := fmt.Sprintf(`{
		Book(filter: {_docID: {_eq: "%s"}}) {
			page_count
		}
	}`, bookID)

	bookResp, err := defraClient.Execute(ctx, bookQuery, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to query book: %w", err)
	}

	var totalPages int
	if books, ok := bookResp.Data["Book"].([]any); ok && len(books) > 0 {
		if book, ok := books[0].(map[string]any); ok {
			if pc, ok := book["page_count"].(float64); ok {
				totalPages = int(pc)
			}
		}
	}

	if totalPages == 0 {
		return nil, fmt.Errorf("book %s has no pages", bookID)
	}

	// Load PDFs from originals directory
	pdfs, err := loadPDFsFromOriginals(homeDir, bookID)
	if err != nil {
		return nil, fmt.Errorf("failed to load PDFs: %w", err)
	}

	if len(pdfs) == 0 {
		return nil, fmt.Errorf("no PDFs found in originals directory for book %s", bookID)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating page processing job", "book_id", bookID, "ocr_providers", cfg.OcrProviders)
	}

	// Job accesses services via svcctx from context passed to Start/OnComplete
	return pjob.New(pjob.Config{
		BookID:           bookID,
		TotalPages:       totalPages,
		HomeDir:          homeDir,
		PDFs:             pdfs,
		OcrProviders:     cfg.OcrProviders,
		BlendProvider:    cfg.BlendProvider,
		LabelProvider:    cfg.LabelProvider,
		MetadataProvider: cfg.MetadataProvider,
		TocProvider:      cfg.TocProvider,
	}), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
// Used by the scheduler to resume interrupted jobs after restart.
func JobFactory(cfg Config) jobs.JobFactory {
	return func(ctx context.Context, id string, metadata map[string]any) (jobs.Job, error) {
		bookID, ok := metadata["book_id"].(string)
		if !ok {
			return nil, fmt.Errorf("missing book_id in job metadata")
		}

		job, err := NewJob(ctx, cfg, bookID)
		if err != nil {
			return nil, err
		}

		// Set the persisted record ID
		job.SetRecordID(id)
		return job, nil
	}
}

// loadPDFsFromOriginals scans the originals directory for PDFs
// and builds PDFInfo with cumulative page ranges.
func loadPDFsFromOriginals(homeDir *home.Dir, bookID string) ([]pjob.PDFInfo, error) {
	originalsDir := homeDir.OriginalsDir(bookID)

	entries, err := os.ReadDir(originalsDir)
	if err != nil {
		return nil, fmt.Errorf("failed to read originals directory: %w", err)
	}

	// Find all PDFs
	var pdfPaths []string
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		if strings.HasSuffix(strings.ToLower(entry.Name()), ".pdf") {
			pdfPaths = append(pdfPaths, filepath.Join(originalsDir, entry.Name()))
		}
	}

	// Sort by numeric suffix
	pdfPaths = sortPDFsByNumber(pdfPaths)

	// Build PDFInfo with cumulative page ranges
	var pdfs []pjob.PDFInfo
	cumulativePage := 1

	for _, pdfPath := range pdfPaths {
		f, err := os.Open(pdfPath)
		if err != nil {
			return nil, fmt.Errorf("failed to open PDF %s: %w", pdfPath, err)
		}
		pageCount, err := api.PageCount(f, nil)
		f.Close()
		if err != nil {
			return nil, fmt.Errorf("failed to get page count for %s: %w", pdfPath, err)
		}

		pdfs = append(pdfs, pjob.PDFInfo{
			Path:      pdfPath,
			StartPage: cumulativePage,
			EndPage:   cumulativePage + pageCount - 1,
		})

		cumulativePage += pageCount
	}

	return pdfs, nil
}

// sortPDFsByNumber sorts PDF paths by their numeric suffix.
// e.g., ["book-2.pdf", "book-1.pdf", "book-10.pdf"] -> ["book-1.pdf", "book-2.pdf", "book-10.pdf"]
func sortPDFsByNumber(paths []string) []string {
	sorted := make([]string, len(paths))
	copy(sorted, paths)

	re := regexp.MustCompile(`-(\d+)\.pdf$`)

	sort.Slice(sorted, func(i, j int) bool {
		mi := re.FindStringSubmatch(strings.ToLower(sorted[i]))
		mj := re.FindStringSubmatch(strings.ToLower(sorted[j]))

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
