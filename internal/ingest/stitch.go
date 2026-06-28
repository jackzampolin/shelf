package ingest

import (
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"github.com/pdfcpu/pdfcpu/pkg/api"
)

var (
	// DefaultPartPattern strips suffixes like "-1" or "_10" from PDF stems.
	DefaultPartPattern = regexp.MustCompile(`[-_](\d+)$`)
	partDigitsPattern  = regexp.MustCompile(`\d+`)
)

// BookParts is a group of PDF paths that should be ingested as one book.
type BookParts struct {
	Name  string
	Parts []string
}

type groupedPart struct {
	path string
	num  int
}

// GroupParts groups multi-part PDF scans by stripping a trailing numeric suffix.
// Non-PDF paths are ignored. Files without a suffix become singleton groups.
func GroupParts(paths []string, pattern *regexp.Regexp) []BookParts {
	if pattern == nil {
		pattern = DefaultPartPattern
	}

	groups := make(map[string]*struct {
		name  string
		parts []groupedPart
	})

	for _, path := range paths {
		if strings.ToLower(filepath.Ext(path)) != ".pdf" {
			continue
		}

		stem := strings.TrimSuffix(filepath.Base(path), filepath.Ext(path))
		name, partNum, ok := partInfo(stem, pattern)
		key := "part:" + name
		if !ok {
			name = stem
			partNum = 0
			key = "single:" + path
		}

		group := groups[key]
		if group == nil {
			group = &struct {
				name  string
				parts []groupedPart
			}{
				name: name,
			}
			groups[key] = group
		}
		group.parts = append(group.parts, groupedPart{path: path, num: partNum})
	}

	result := make([]BookParts, 0, len(groups))
	for _, group := range groups {
		sort.Slice(group.parts, func(i, j int) bool {
			if group.parts[i].num != group.parts[j].num {
				return group.parts[i].num < group.parts[j].num
			}
			return group.parts[i].path < group.parts[j].path
		})

		parts := make([]string, len(group.parts))
		for i, part := range group.parts {
			parts[i] = part.path
		}
		result = append(result, BookParts{Name: group.name, Parts: parts})
	}

	sort.Slice(result, func(i, j int) bool {
		if result[i].Name != result[j].Name {
			return result[i].Name < result[j].Name
		}
		if len(result[i].Parts) == 0 || len(result[j].Parts) == 0 {
			return len(result[i].Parts) < len(result[j].Parts)
		}
		return result[i].Parts[0] < result[j].Parts[0]
	})

	return result
}

func partInfo(stem string, pattern *regexp.Regexp) (string, int, bool) {
	matches := pattern.FindAllStringSubmatchIndex(stem, -1)
	for i := len(matches) - 1; i >= 0; i-- {
		match := matches[i]
		if len(match) < 2 || match[1] != len(stem) {
			continue
		}

		numberText := ""
		if len(match) >= 4 && match[2] >= 0 && match[3] >= 0 {
			numberText = stem[match[2]:match[3]]
		} else {
			numberText = lastDigits(stem[match[0]:match[1]])
		}
		if numberText == "" {
			continue
		}

		num, err := strconv.Atoi(numberText)
		if err != nil {
			continue
		}

		name := stem[:match[0]]
		if name == "" {
			name = stem
		}
		return name, num, true
	}

	return stem, 0, false
}

func lastDigits(s string) string {
	matches := partDigitsPattern.FindAllString(s, -1)
	if len(matches) == 0 {
		return ""
	}
	return matches[len(matches)-1]
}

// StitchPDF merges PDF parts into out. A single input is copied.
func StitchPDF(parts []string, out string) error {
	if len(parts) == 0 {
		return fmt.Errorf("no PDF parts provided")
	}
	if out == "" {
		return fmt.Errorf("output path is required")
	}
	if err := os.MkdirAll(filepath.Dir(out), 0o755); err != nil {
		return fmt.Errorf("failed to create output directory: %w", err)
	}

	if len(parts) == 1 {
		return copyFile(parts[0], out)
	}

	if err := api.MergeCreateFile(parts, out, false, nil); err != nil {
		return fmt.Errorf("failed to stitch PDFs: %w", err)
	}
	return nil
}
