package common

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"

	"github.com/pdfcpu/pdfcpu/pkg/api"

	"github.com/jackzampolin/shelf/internal/home"
)

// PDFInfo describes a PDF file and its page range.
type PDFInfo struct {
	Path      string // Full path to the PDF
	StartPage int    // First page number (1-indexed, cumulative)
	EndPage   int    // Last page number (inclusive)
}

// PDFList is a slice of PDFInfo with helper methods.
type PDFList []PDFInfo

// FindPDFForPage returns the PDF path and page number within that PDF for a given output page number.
// Returns empty string and 0 if page is out of range.
func (pdfs PDFList) FindPDFForPage(pageNum int) (pdfPath string, pageInPDF int) {
	for _, pdf := range pdfs {
		if pageNum >= pdf.StartPage && pageNum <= pdf.EndPage {
			// pageInPDF is 1-indexed within this PDF
			pageInPDF = pageNum - pdf.StartPage + 1
			return pdf.Path, pageInPDF
		}
	}
	return "", 0
}

// LoadPDFsFromOriginals scans the originals directory for PDFs
// and builds PDFInfo with cumulative page ranges.
func LoadPDFsFromOriginals(homeDir *home.Dir, bookID string) (PDFList, error) {
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
	var pdfs PDFList
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

		pdfs = append(pdfs, PDFInfo{
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
			var ni, nj int
			fmt.Sscanf(mi[1], "%d", &ni)
			fmt.Sscanf(mj[1], "%d", &nj)
			return ni < nj
		}

		// Otherwise sort lexicographically
		return sorted[i] < sorted[j]
	})

	return sorted
}
