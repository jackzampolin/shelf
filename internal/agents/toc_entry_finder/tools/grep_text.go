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
	InBackMatter    bool     `json:"in_back_matter"`
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

	// Estimate back matter start (last 20% of book)
	backMatterStart := int(float64(t.book.TotalPages) * 0.8)

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
			snippet := strings.TrimSpace(text[start:end])
			snippet = strings.ReplaceAll(snippet, "\n", " ")
			snippets = append(snippets, "..."+snippet+"...")
		}

		matches = append(matches, GrepMatch{
			ScanPage:        pageNum,
			MatchCount:      len(allMatches),
			ContextSnippets: snippets,
			InBackMatter:    pageNum >= backMatterStart,
		})
	}

	if len(matches) == 0 {
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
	summary := buildGrepSummary(matches, clusters, backMatterStart)

	return jsonSuccess(map[string]any{
		"query":    query,
		"matches":  matches,
		"clusters": clusters,
		"summary":  summary,
		"message":  fmt.Sprintf("Found %d matches across %d pages", sumMatchCounts(matches), len(matches)),
	}), nil
}

// Cluster represents a contiguous group of pages with matches.
type Cluster struct {
	StartPage int `json:"start_page"`
	EndPage   int `json:"end_page"`
	PageCount int `json:"page_count"`
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

func buildGrepSummary(matches []GrepMatch, clusters []Cluster, backMatterStart int) string {
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
			lines = append(lines, fmt.Sprintf("  → Pages %d-%d (%d pages) - first page is likely chapter start",
				c.StartPage, c.EndPage, c.PageCount))
		}
	}

	if backMatterMatches > 0 && backMatterMatches == len(matches) {
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
