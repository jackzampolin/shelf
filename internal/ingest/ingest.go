// Package ingest handles book scan ingestion from PDF files.
package ingest

import (
	"path/filepath"
	"regexp"
	"sort"
	"strings"
)

// sortPDFsByNumber sorts PDF paths by their numeric suffix.
// e.g., ["book-2.pdf", "book-1.pdf", "book-10.pdf"] -> ["book-1.pdf", "book-2.pdf", "book-10.pdf"]
func sortPDFsByNumber(paths []string) []string {
	sorted := make([]string, len(paths))
	copy(sorted, paths)

	// Reuse the same suffix logic as GroupParts so ordering is separator- and
	// extension-agnostic (handles "-N"/"_N", .pdf/.PDF). The old hyphen-and-
	// lowercase-only regex sorted underscore/uppercase parts lexically, which
	// merged "volume_10" before "volume_2".
	partNum := func(p string) (int, bool) {
		stem := strings.TrimSuffix(filepath.Base(p), filepath.Ext(p))
		_, n, ok := partInfo(stem, DefaultPartPattern)
		return n, ok
	}

	sort.Slice(sorted, func(i, j int) bool {
		ni, oki := partNum(sorted[i])
		nj, okj := partNum(sorted[j])
		if oki && okj {
			if ni != nj {
				return ni < nj
			}
			return sorted[i] < sorted[j]
		}
		if oki != okj {
			return !oki // files without a numeric suffix sort first
		}
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
