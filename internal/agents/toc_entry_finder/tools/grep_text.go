package tools

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

const (
	maxGrepSnippetPages = 12
	maxGrepSnippetRunes = 160
)

// GrepMatch represents a match on a single page.
type GrepMatch struct {
	ScanPage        int      `json:"scan_page"`
	MatchCount      int      `json:"match_count"`
	ContextSnippets []string `json:"context_snippets,omitempty"`
	InBackMatter    bool     `json:"in_back_matter"`
	InExpectedRange bool     `json:"in_expected_scan_window,omitempty"`
}

func grepTextTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "grep_text",
			Description: "Search for text patterns across all pages in the book. Returns pages where the pattern matches along with context snippets. KEY INSIGHT: Running headers create clusters - if a chapter title appears on pages 45-62, page 45 is likely the chapter START. Supports regex patterns.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query": map[string]any{
						"type":        "string",
						"description": "Text or regex pattern to search for (e.g., 'Chapter 5', 'CHAPTER.*FIVE', 'Planning Torch')",
					},
				},
				"required": []string{"query"},
			}),
		},
	}
}

func (t *TocEntryFinderTools) grepText(ctx context.Context, query string) (string, error) {
	if query == "" {
		return jsonError("query is required"), nil
	}

	// Compile regex (case insensitive)
	re, err := regexp.Compile("(?i)" + query)
	if err != nil {
		// If regex fails, try literal match
		re = regexp.MustCompile("(?i)" + regexp.QuoteMeta(query))
	}

	backMatterStart := t.effectiveBackMatterStart()
	expectedStart, expectedEnd, hasExpectedWindow := t.expectedScanWindow()

	var matches []GrepMatch

	// Search all pages (data already in BookState)
	for pageNum := 1; pageNum <= t.book.TotalPages; pageNum++ {
		text, err := t.getPageOcrMarkdown(ctx, pageNum)
		if err != nil {
			continue // Skip pages without OCR
		}

		allMatches := re.FindAllStringIndex(text, -1)
		if len(allMatches) == 0 {
			continue
		}

		// Extract context snippets (up to 3)
		var snippets []string
		for i, match := range allMatches {
			if i >= 3 {
				break
			}
			start := match[0] - 50
			if start < 0 {
				start = 0
			}
			end := match[1] + 50
			if end > len(text) {
				end = len(text)
			}
			snippet := strings.TrimSpace(stripOCRMarkup(text[start:end]))
			snippet = strings.ReplaceAll(snippet, "\n", " ")
			snippets = append(snippets, "..."+truncateRunes(snippet, maxGrepSnippetRunes)+"...")
		}

		matches = append(matches, GrepMatch{
			ScanPage:        pageNum,
			MatchCount:      len(allMatches),
			ContextSnippets: snippets,
			InBackMatter:    backMatterStart > 0 && pageNum >= backMatterStart,
			InExpectedRange: hasExpectedWindow && pageNum >= expectedStart && pageNum <= expectedEnd,
		})
	}

	if len(matches) == 0 {
		approxMatches := t.approximateTargetTitleMatches(ctx)
		if len(approxMatches) > 0 {
			clusters := identifyClusters(approxMatches)
			for i := range clusters {
				clusters[i].NearExpectedScanWindow = hasExpectedWindow && rangesOverlap(clusters[i].StartPage, clusters[i].EndPage, expectedStart, expectedEnd)
			}
			approxMatches, snippetsIncluded, snippetsOmitted := compactGrepMatchSnippets(approxMatches, clusters, hasExpectedWindow)
			summary := buildGrepSummary(approxMatches, clusters, backMatterStart, t.targetIsBackMatter)
			return jsonSuccess(map[string]any{
				"query":                   query,
				"matches":                 approxMatches,
				"clusters":                clusters,
				"summary":                 summary,
				"approximate_title_match": true,
				"snippets_included_pages": snippetsIncluded,
				"snippets_omitted_pages":  snippetsOmitted,
				"message":                 fmt.Sprintf("No exact matches for %q. Found approximate matches for target title %q across %d pages.", query, t.entryTitle(), len(approxMatches)),
			}), nil
		}
		return jsonSuccess(map[string]any{
			"query":   query,
			"matches": []GrepMatch{},
			"message": "No matches found. Try different query variations (spelled out numbers, Roman numerals, title only).",
		}), nil
	}

	// Sort by page number
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].ScanPage < matches[j].ScanPage
	})

	// Identify clusters
	clusters := identifyClusters(matches)
	for i := range clusters {
		clusters[i].NearExpectedScanWindow = hasExpectedWindow && rangesOverlap(clusters[i].StartPage, clusters[i].EndPage, expectedStart, expectedEnd)
	}
	matches, snippetsIncluded, snippetsOmitted := compactGrepMatchSnippets(matches, clusters, hasExpectedWindow)
	summary := buildGrepSummary(matches, clusters, backMatterStart, t.targetIsBackMatter)

	return jsonSuccess(map[string]any{
		"query":                   query,
		"matches":                 matches,
		"clusters":                clusters,
		"summary":                 summary,
		"snippets_included_pages": snippetsIncluded,
		"snippets_omitted_pages":  snippetsOmitted,
		"message":                 fmt.Sprintf("Found %d matches across %d pages", sumMatchCounts(matches), len(matches)),
	}), nil
}

func (t *TocEntryFinderTools) approximateTargetTitleMatches(ctx context.Context) []GrepMatch {
	title := t.entryTitle()
	if title == "" || t.book == nil {
		return nil
	}

	backMatterStart := t.effectiveBackMatterStart()
	expectedStart, expectedEnd, hasExpectedWindow := t.expectedScanWindow()

	var matches []GrepMatch
	for pageNum := 1; pageNum <= t.book.TotalPages; pageNum++ {
		text, err := t.getPageOcrMarkdown(ctx, pageNum)
		if err != nil {
			continue
		}
		if !normalizedContains(stripOCRMarkup(text), title) {
			continue
		}
		snippet := strings.TrimSpace(stripOCRMarkup(text))
		snippet = strings.ReplaceAll(snippet, "\n", " ")
		matches = append(matches, GrepMatch{
			ScanPage:        pageNum,
			MatchCount:      1,
			ContextSnippets: []string{"..." + truncateRunes(snippet, maxGrepSnippetRunes) + "..."},
			InBackMatter:    backMatterStart > 0 && pageNum >= backMatterStart,
			InExpectedRange: hasExpectedWindow && pageNum >= expectedStart && pageNum <= expectedEnd,
		})
	}
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].ScanPage < matches[j].ScanPage
	})
	return matches
}

func (t *TocEntryFinderTools) entryTitle() string {
	if t == nil || t.entry == nil {
		return ""
	}
	return strings.TrimSpace(t.entry.Title)
}

// Cluster represents a contiguous group of pages with matches.
type Cluster struct {
	StartPage              int  `json:"start_page"`
	EndPage                int  `json:"end_page"`
	PageCount              int  `json:"page_count"`
	NearExpectedScanWindow bool `json:"near_expected_scan_window,omitempty"`
}

// identifyClusters finds contiguous page clusters (gaps of <= 3 pages allowed).
func identifyClusters(matches []GrepMatch) []Cluster {
	if len(matches) == 0 {
		return nil
	}

	var clusters []Cluster
	currentCluster := Cluster{
		StartPage: matches[0].ScanPage,
		EndPage:   matches[0].ScanPage,
		PageCount: 1,
	}

	for i := 1; i < len(matches); i++ {
		if matches[i].ScanPage-currentCluster.EndPage <= 3 {
			// Continue cluster
			currentCluster.EndPage = matches[i].ScanPage
			currentCluster.PageCount++
		} else {
			// Save current cluster if it has multiple pages
			if currentCluster.PageCount >= 2 {
				clusters = append(clusters, currentCluster)
			}
			// Start new cluster
			currentCluster = Cluster{
				StartPage: matches[i].ScanPage,
				EndPage:   matches[i].ScanPage,
				PageCount: 1,
			}
		}
	}

	// Don't forget the last cluster
	if currentCluster.PageCount >= 2 {
		clusters = append(clusters, currentCluster)
	}

	return clusters
}

func compactGrepMatchSnippets(matches []GrepMatch, clusters []Cluster, hasExpectedWindow bool) ([]GrepMatch, int, int) {
	if len(matches) == 0 {
		return matches, 0, 0
	}

	keepPages := map[int]bool{}
	for _, cluster := range clusters {
		keepPages[cluster.StartPage] = true
		keepPages[cluster.EndPage] = true
	}
	if hasExpectedWindow {
		for _, match := range matches {
			if !match.InExpectedRange {
				continue
			}
			keepPages[match.ScanPage] = true
			if len(keepPages) >= maxGrepSnippetPages {
				break
			}
		}
	}
	if len(keepPages) == 0 {
		for _, match := range matches {
			keepPages[match.ScanPage] = true
			if len(keepPages) >= maxGrepSnippetPages {
				break
			}
		}
	}

	out := make([]GrepMatch, len(matches))
	copy(out, matches)
	included := 0
	omitted := 0
	for i := range out {
		if len(out[i].ContextSnippets) == 0 {
			continue
		}
		if keepPages[out[i].ScanPage] && included < maxGrepSnippetPages {
			included++
			continue
		}
		out[i].ContextSnippets = nil
		omitted++
	}
	return out, included, omitted
}

func buildGrepSummary(matches []GrepMatch, clusters []Cluster, backMatterStart int, targetIsBackMatter bool) string {
	var lines []string

	// Check for back matter contamination
	backMatterMatches := 0
	for _, m := range matches {
		if m.InBackMatter {
			backMatterMatches++
		}
	}

	if len(clusters) > 0 {
		lines = append(lines, fmt.Sprintf("CLUSTERS DETECTED: %d dense cluster(s)", len(clusters)))
		for _, c := range clusters {
			expectedNote := ""
			if c.NearExpectedScanWindow {
				expectedNote = " near expected scan window"
			}
			lines = append(lines, fmt.Sprintf("  -> Pages %d-%d (%d pages)%s - first page is likely section start",
				c.StartPage, c.EndPage, c.PageCount, expectedNote))
		}
		lines = append(lines, "Verify the first cluster page with get_page_ocr. If it shows the target title in the page header plus body text, call write_result even if OCR did not detect a formal chapter heading.")
	}

	if backMatterMatches > 0 && targetIsBackMatter {
		lines = append(lines, "")
		lines = append(lines, fmt.Sprintf("Back matter matches are plausible for this target (page %d+). Verify the exact entry start before writing the result.", backMatterStart))
	} else if backMatterMatches > 0 && backMatterMatches == len(matches) {
		lines = append(lines, "")
		lines = append(lines, fmt.Sprintf("⚠️ WARNING: All %d matches are in back matter (page %d+)", backMatterMatches, backMatterStart))
		lines = append(lines, "   These are likely footnote references. Try alternative queries.")
	} else if backMatterMatches > 0 {
		lines = append(lines, "")
		lines = append(lines, fmt.Sprintf("Note: %d of %d matches are in back matter (page %d+) - likely footnotes", backMatterMatches, len(matches), backMatterStart))
	}

	if len(matches) == 1 {
		lines = append(lines, "")
		lines = append(lines, "Single isolated match - verify with OCR/vision, consider query variations")
	}

	return strings.Join(lines, "\n")
}

func sumMatchCounts(matches []GrepMatch) int {
	total := 0
	for _, m := range matches {
		total += m.MatchCount
	}
	return total
}

func rangesOverlap(aStart, aEnd, bStart, bEnd int) bool {
	return aStart <= bEnd && bStart <= aEnd
}
