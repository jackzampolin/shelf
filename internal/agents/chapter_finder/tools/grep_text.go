package tools

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
)

// GrepMatch represents a match on a single page.
type GrepMatch struct {
	ScanPage        int      `json:"scan_page"`
	MatchCount      int      `json:"match_count"`
	ContextSnippets []string `json:"context_snippets,omitempty"`
	InExcludedRange bool     `json:"in_excluded_range"`
}

// maxGrepMatches bounds how many per-page match records are serialized back to
// the agent. Clusters are computed over the full match set first; only the
// output list is capped, so broad queries cannot exceed the model context.
const maxGrepMatches = 50

func grepTextTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "grep_text",
			Description: "Search for text patterns across all pages in the book. Returns pages where the pattern matches. KEY INSIGHT: Running headers create clusters - if a chapter title appears on pages 45-62, page 45 is likely the chapter START. Supports regex patterns. Matches in excluded ranges are marked.",
			Parameters: mustMarshal(map[string]any{
				"type": "object",
				"properties": map[string]any{
					"query": map[string]any{
						"type":        "string",
						"description": "Text or regex pattern to search for (e.g., 'Chapter 14', 'CHAPTER.*FOURTEEN', '14')",
					},
				},
				"required": []string{"query"},
			}),
		},
	}
}

func (t *ChapterFinderTools) grepText(ctx context.Context, query string) (string, error) {
	if query == "" {
		return jsonError("query is required"), nil
	}

	// Compile regex (case insensitive)
	re, err := regexp.Compile("(?i)" + query)
	if err != nil {
		// If regex fails, try literal match
		re = regexp.MustCompile("(?i)" + regexp.QuoteMeta(query))
	}

	var matches []GrepMatch

	// Search all pages
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
			snippet := strings.TrimSpace(text[start:end])
			snippet = strings.ReplaceAll(snippet, "\n", " ")
			snippets = append(snippets, "..."+snippet+"...")
		}

		matches = append(matches, GrepMatch{
			ScanPage:        pageNum,
			MatchCount:      len(allMatches),
			ContextSnippets: snippets,
			InExcludedRange: t.isInExcludedRange(pageNum),
		})
	}

	if len(matches) == 0 {
		return jsonSuccess(map[string]any{
			"query":   query,
			"matches": []GrepMatch{},
			"message": "No matches found. Try different query variations (spelled out numbers, Roman numerals, just the number).",
		}), nil
	}

	// Sort by page number
	sort.Slice(matches, func(i, j int) bool {
		return matches[i].ScanPage < matches[j].ScanPage
	})

	// Filter out excluded matches for cluster analysis
	var validMatches []GrepMatch
	for _, m := range matches {
		if !m.InExcludedRange {
			validMatches = append(validMatches, m)
		}
	}

	// Identify clusters (only from non-excluded pages)
	clusters := identifyClusters(validMatches)
	summary := buildGrepSummary(matches, clusters, len(t.excludedRanges) > 0)

	totalMatchPages := len(matches)
	matchesTruncated := false
	if len(matches) > maxGrepMatches {
		matchesTruncated = true
		matches = capMatches(matches, clusters, t.entryNearPage())
	}

	return jsonSuccess(map[string]any{
		"query":               query,
		"matches":             matches,
		"matches_truncated":   matchesTruncated,
		"total_match_pages":   totalMatchPages,
		"dropped_match_pages": totalMatchPages - len(matches),
		"clusters":            clusters,
		"summary":             summary,
		"message":             fmt.Sprintf("Found matches on %d pages (showing %d)", totalMatchPages, len(matches)),
	}), nil
}

// entryNearPage returns the entry's expected page (0 if unknown), used to bias
// which matches survive truncation toward where the chapter is expected.
func (t *ChapterFinderTools) entryNearPage() int {
	if t.entry != nil {
		return t.entry.ExpectedNearPage
	}
	return 0
}

// capMatches bounds the returned match set to maxGrepMatches without dropping
// chapter-start candidates. It always keeps every cluster's first page and every
// isolated (non-clustered) non-excluded match — those are the likely chapter
// starts — then fills the remaining slots with pages nearest the expected page.
// Result is returned sorted by page number.
func capMatches(matches []GrepMatch, clusters []Cluster, near int) []GrepMatch {
	inCluster := func(p int) bool {
		for _, c := range clusters {
			if p >= c.StartPage && p <= c.EndPage {
				return true
			}
		}
		return false
	}
	clusterStart := make(map[int]bool, len(clusters))
	for _, c := range clusters {
		clusterStart[c.StartPage] = true
	}

	byNear := func(s []GrepMatch) {
		sort.Slice(s, func(i, j int) bool {
			li, lj := absInt(s[i].ScanPage-near), absInt(s[j].ScanPage-near)
			if li == lj {
				return s[i].ScanPage < s[j].ScanPage
			}
			return li < lj
		})
	}

	var mustKeep, rest []GrepMatch
	for _, m := range matches {
		if !m.InExcludedRange && (clusterStart[m.ScanPage] || !inCluster(m.ScanPage)) {
			mustKeep = append(mustKeep, m)
		} else {
			rest = append(rest, m)
		}
	}

	var kept []GrepMatch
	if len(mustKeep) >= maxGrepMatches {
		byNear(mustKeep)
		kept = mustKeep[:maxGrepMatches]
	} else {
		byNear(rest)
		kept = mustKeep
		for _, m := range rest {
			if len(kept) >= maxGrepMatches {
				break
			}
			kept = append(kept, m)
		}
	}

	sort.Slice(kept, func(i, j int) bool { return kept[i].ScanPage < kept[j].ScanPage })
	return kept
}

// Cluster represents a contiguous group of pages with matches.
type Cluster struct {
	StartPage int `json:"start_page"`
	EndPage   int `json:"end_page"`
	PageCount int `json:"page_count"`
}

// identifyClusters finds contiguous page clusters (gaps of <= 2 pages allowed).
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

func buildGrepSummary(matches []GrepMatch, clusters []Cluster, hasExcludedRanges bool) string {
	var lines []string

	// Count excluded matches
	excludedCount := 0
	for _, m := range matches {
		if m.InExcludedRange {
			excludedCount++
		}
	}

	if len(clusters) > 0 {
		lines = append(lines, fmt.Sprintf("CLUSTERS DETECTED: %d dense cluster(s)", len(clusters)))
		for _, c := range clusters {
			lines = append(lines, fmt.Sprintf("  → Pages %d-%d (%d pages) - first page is likely chapter start",
				c.StartPage, c.EndPage, c.PageCount))
		}
	}

	if excludedCount > 0 {
		lines = append(lines, "")
		lines = append(lines, fmt.Sprintf("⚠️ NOTE: %d of %d matches are in EXCLUDED ranges (back matter) - ignore those",
			excludedCount, len(matches)))
	}

	if excludedCount == len(matches) && hasExcludedRanges {
		lines = append(lines, "")
		lines = append(lines, "All matches are in excluded ranges. Try different query variations.")
	}

	if len(matches) == 1 {
		lines = append(lines, "")
		if matches[0].InExcludedRange {
			lines = append(lines, "Single match is in excluded range - likely not the chapter start")
		} else {
			lines = append(lines, "Single isolated match - verify with OCR/vision")
		}
	}

	return strings.Join(lines, "\n")
}

func absInt(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
