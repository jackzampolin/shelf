package tools

import (
	"context"
	"fmt"
	"regexp"
	"sort"
	"strings"

	"github.com/jackzampolin/shelf/internal/providers"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// GrepReport contains categorized keyword search results.
type GrepReport struct {
	SearchRange        string               `json:"search_range"`
	TotalPagesSearched int                  `json:"total_pages_searched"`
	PagesWithData      int                  `json:"pages_with_data"`
	FailedPages        []int                `json:"failed_pages,omitempty"`
	CategorizedPages   map[string][]int     `json:"categorized_pages"`
	PageDetails        map[int]CategoryHits `json:"page_details"`
}

// CategoryHits maps category names to found keywords.
type CategoryHits map[string][]string

func grepReportTool() providers.Tool {
	return providers.Tool{
		Type: "function",
		Function: providers.ToolFunction{
			Name:        "get_frontmatter_grep_report",
			Description: "Get keyword search report showing categorized keyword matches in front matter. FREE operation (no LLM cost). Returns categorized_pages (pages grouped by keyword type: toc, structure, front_matter, back_matter) and page_details (which keywords appear on each page). Summary includes clustering analysis.",
			Parameters:  mustMarshal(map[string]any{"type": "object", "properties": map[string]any{}, "required": []string{}}),
		},
	}
}

func (t *ToCFinderTools) getFrontmatterGrepReport(ctx context.Context) (string, error) {
	if t.grepReportCache != nil {
		summary := summarizeGrepReport(t.grepReportCache)
		return jsonSuccess(map[string]any{
			"report":  t.grepReportCache,
			"summary": summary,
			"message": "Grep report generated. Check 'categorized_pages' for keyword groupings and 'summary' for actionable recommendations.",
		}), nil
	}

	// Generate grep report by searching pages
	maxPages := 50
	if t.totalPages < maxPages {
		maxPages = t.totalPages
	}

	report := &GrepReport{
		SearchRange:        fmt.Sprintf("1-%d", maxPages),
		TotalPagesSearched: maxPages,
		CategorizedPages:   make(map[string][]int),
		PageDetails:        make(map[int]CategoryHits),
	}

	// Preload all pages in one batch query if pageReader is available
	if t.pageReader != nil {
		if err := t.pageReader.PreloadPages(ctx, 1, maxPages); err != nil {
			// Log but continue - fallback to per-page queries will work
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("PreloadPages failed, falling back to per-page queries",
					"book_id", t.bookID,
					"max_pages", maxPages,
					"error", err)
			}
		}
	}

	// Query blended text for each page, tracking failures
	var failedPages []int
	pagesWithData := 0

	for pageNum := 1; pageNum <= maxPages; pageNum++ {
		text, err := t.getPageBlendedText(ctx, pageNum)
		if err != nil {
			failedPages = append(failedPages, pageNum)
			continue
		}
		pagesWithData++

		categories := searchCategorizedPatterns(text)
		if len(categories) > 0 {
			report.PageDetails[pageNum] = categories
			for category := range categories {
				report.CategorizedPages[category] = append(report.CategorizedPages[category], pageNum)
			}
		}
	}

	report.PagesWithData = pagesWithData
	report.FailedPages = failedPages

	t.grepReportCache = report
	summary := summarizeGrepReport(report)

	return jsonSuccess(map[string]any{
		"report":  report,
		"summary": summary,
		"message": "Grep report generated. Check 'categorized_pages' for keyword groupings and 'summary' for actionable recommendations.",
	}), nil
}

// Keyword patterns for grep search
var keywordCategories = map[string][]string{
	"toc": {
		`\bTable of Contents\b`,
		`\bTABLE OF CONTENTS\b`,
		`\bContents\b`,
		`\bCONTENTS\b`,
		`\bOrder of Battle\b`,
		`\bORDER OF BATTLE\b`,
		`\bList of Chapters\b`,
		`\bLIST OF CHAPTERS\b`,
		`\bChapter Overview\b`,
		`\bSynopsis\b`,
		`\bSYNOPSIS\b`,
	},
	"front_matter": {
		`\bPreface\b`,
		`\bPREFACE\b`,
		`\bAuthor's Note\b`,
		`\bForeword\b`,
		`\bIntroduction\b`,
		`\bINTRODUCTION\b`,
		`\bPrologue\b`,
		`\bAcknowledgments\b`,
		`\bAcknowledgements\b`,
		`\bACKNOWLEDGMENTS\b`,
		`\bDedication\b`,
		`\bDedicated to\b`,
		`\bAbout the Author\b`,
		`\bAbout The Author\b`,
	},
	"structure": {
		`\bChapter\s+\d+`,
		`\bCHAPTER\s+\d+`,
		`^Chapter\s+[IVX]+`,
		`\bPart\s+\d+`,
		`\bPART\s+\d+`,
		`^Part\s+[IVX]+`,
		`\bSection\s+\d+`,
	},
	"back_matter": {
		`\bAppendix\b`,
		`\bAPPENDIX\b`,
		`\bBibliography\b`,
		`\bWorks Cited\b`,
		`\bReferences\b`,
		`\bIndex\b`,
		`\bINDEX\b`,
		`\bEpilogue\b`,
		`\bAfterword\b`,
		`\bEndnotes\b`,
		`\bNotes\b`,
	},
}

// searchCategorizedPatterns searches text for keyword patterns.
func searchCategorizedPatterns(text string) CategoryHits {
	categories := make(CategoryHits)

	for category, patterns := range keywordCategories {
		found := make(map[string]bool)
		for _, pattern := range patterns {
			re, err := regexp.Compile("(?mi)" + pattern)
			if err != nil {
				continue
			}
			matches := re.FindAllString(text, -1)
			for _, match := range matches {
				found[match] = true
			}
		}
		if len(found) > 0 {
			keywords := make([]string, 0, len(found))
			for k := range found {
				keywords = append(keywords, k)
			}
			sort.Strings(keywords)
			categories[category] = keywords
		}
	}

	return categories
}

// summarizeGrepReport generates an actionable summary.
func summarizeGrepReport(report *GrepReport) string {
	var lines []string
	lines = append(lines, fmt.Sprintf("Searched: %s (%d pages with OCR data)", report.SearchRange, report.PagesWithData))

	// Warn about missing data
	if len(report.FailedPages) > 0 {
		lines = append(lines, "")
		lines = append(lines, fmt.Sprintf("⚠️  WARNING: %d pages missing OCR data: %v", len(report.FailedPages), report.FailedPages))
		lines = append(lines, "   These pages could not be searched - ToC might be on an unsearched page!")
	}
	lines = append(lines, "")

	categorized := report.CategorizedPages
	if len(categorized) == 0 {
		lines = append(lines, "No keywords found in searchable pages.")
		if len(report.FailedPages) > 0 {
			lines = append(lines, "Consider visually checking failed pages - they may contain ToC.")
		}
		return strings.Join(lines, "\n")
	}

	// ToC keywords (highest priority)
	if pages, ok := categorized["toc"]; ok && len(pages) > 0 {
		lines = append(lines, fmt.Sprintf("✓ TOC KEYWORDS: pages %v", pages))
		lines = append(lines, "  → Check these pages first (direct ToC indicators)")
		lines = append(lines, "")
	}

	// Structure keywords (strong signal if clustered)
	if pages, ok := categorized["structure"]; ok && len(pages) > 0 {
		clusters := identifyClusters(pages, 3, 2)
		if len(clusters) > 0 {
			lines = append(lines, fmt.Sprintf("✓ STRUCTURE CLUSTERING: %d cluster(s) found", len(clusters)))
			for _, cluster := range clusters {
				pageRange := fmt.Sprintf("%d-%d", cluster[0], cluster[len(cluster)-1])
				if len(cluster) == 1 {
					pageRange = fmt.Sprintf("%d", cluster[0])
				}
				lines = append(lines, fmt.Sprintf("  → Pages %s (%d pages)", pageRange, len(cluster)))
			}
			lines = append(lines, "  Note: Dense clustering of Chapter/Part = likely ToC listing")
			lines = append(lines, "")
		} else {
			lines = append(lines, fmt.Sprintf("• Structure keywords: scattered across %d pages (not clustered)", len(pages)))
			lines = append(lines, "")
		}
	}

	// Front matter
	if pages, ok := categorized["front_matter"]; ok && len(pages) > 0 {
		displayPages := pages
		if len(displayPages) > 5 {
			displayPages = pages[:5]
		}
		lines = append(lines, fmt.Sprintf("• Front matter: pages %v", displayPages))
		if len(pages) > 5 {
			lines = append(lines, fmt.Sprintf("  (+%d more)", len(pages)-5))
		}
		lines = append(lines, "")
	}

	// Back matter
	if pages, ok := categorized["back_matter"]; ok && len(pages) > 0 {
		displayPages := pages
		if len(displayPages) > 5 {
			displayPages = pages[:5]
		}
		lines = append(lines, fmt.Sprintf("• Back matter: pages %v", displayPages))
		if len(pages) > 5 {
			lines = append(lines, fmt.Sprintf("  (+%d more)", len(pages)-5))
		}
		lines = append(lines, "")
	}

	// Recommendation
	lines = append(lines, "RECOMMENDATION:")
	if _, ok := categorized["toc"]; ok {
		lines = append(lines, "  Start with TOC keyword pages")
	} else if structPages, ok := categorized["structure"]; ok {
		clusters := identifyClusters(structPages, 3, 2)
		if len(clusters) > 0 {
			first := clusters[0]
			lines = append(lines, fmt.Sprintf("  Check structure cluster: pages %d-%d", first[0], first[len(first)-1]))
		}
	} else if fmPages, ok := categorized["front_matter"]; ok {
		displayPages := fmPages
		if len(displayPages) > 3 {
			displayPages = fmPages[:3]
		}
		lines = append(lines, fmt.Sprintf("  Scan front matter region around pages %v", displayPages))
	} else {
		lines = append(lines, "  Sequential scan of front matter (pages 1-20)")
	}

	return strings.Join(lines, "\n")
}

// identifyClusters finds clusters of consecutive pages.
func identifyClusters(pages []int, minSize, maxGap int) [][]int {
	if len(pages) == 0 {
		return nil
	}

	sorted := make([]int, len(pages))
	copy(sorted, pages)
	sort.Ints(sorted)

	var clusters [][]int
	currentCluster := []int{sorted[0]}

	for i := 1; i < len(sorted); i++ {
		if sorted[i]-currentCluster[len(currentCluster)-1] <= maxGap {
			currentCluster = append(currentCluster, sorted[i])
		} else {
			if len(currentCluster) >= minSize {
				clusters = append(clusters, currentCluster)
			}
			currentCluster = []int{sorted[i]}
		}
	}

	if len(currentCluster) >= minSize {
		clusters = append(clusters, currentCluster)
	}

	return clusters
}
