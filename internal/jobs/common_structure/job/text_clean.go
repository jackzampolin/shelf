package job

import (
	"strings"
	"unicode"
)

// PageData holds data needed to clean a page's text.
type PageData struct {
	ScanPage              int
	Markdown              string
	PrintedPage           *string
	RunningHeader         *string
	HasPageNumberInHeader bool
}

// CleanPageText mechanically cleans a page's text by removing running header and page number.
// Common patterns:
// - "**6 / The Accidental President**" (page number / running header)
// - "6 / The Accidental President" (without bold)
// - "The Accidental President / 6"
// - Just page number alone on a line
func CleanPageText(pageData *PageData) string {
	text := pageData.Markdown
	lines := strings.Split(text, "\n")

	if len(lines) == 0 {
		return text
	}

	// Check first few lines for header pattern
	var cleanedLines []string
	headerRemoved := false

	for i, line := range lines {
		// Only check first 3 lines for headers
		if i < 3 && !headerRemoved {
			if isHeaderLine(line, pageData) {
				headerRemoved = true
				continue
			}
		}
		cleanedLines = append(cleanedLines, line)
	}

	// Strip leading/trailing whitespace but preserve internal structure
	return strings.TrimSpace(strings.Join(cleanedLines, "\n"))
}

// isHeaderLine detects if a line is a running header/page number to remove.
func isHeaderLine(line string, pageData *PageData) bool {
	stripped := strings.TrimSpace(line)

	if stripped == "" {
		return false
	}

	// Remove markdown bold markers for comparison
	plain := strings.ReplaceAll(stripped, "**", "")
	plain = strings.ReplaceAll(plain, "*", "")

	// Pattern: "6 / Title" or "Title / 6"
	if strings.Contains(plain, "/") {
		parts := strings.Split(plain, "/")
		if len(parts) == 2 {
			p1 := strings.TrimSpace(parts[0])
			p2 := strings.TrimSpace(parts[1])

			// Check if one part is the page number
			if pageData.PrintedPage != nil {
				pnl := *pageData.PrintedPage
				if p1 == pnl || p2 == pnl {
					return true
				}
			}

			// Check if one part matches running header
			if pageData.RunningHeader != nil {
				headerLower := strings.ToLower(*pageData.RunningHeader)
				if strings.ToLower(p1) == headerLower || strings.ToLower(p2) == headerLower {
					return true
				}
			}
		}
	}

	// Pattern: Just the running header alone
	if pageData.RunningHeader != nil {
		if strings.ToLower(plain) == strings.ToLower(*pageData.RunningHeader) {
			return true
		}
	}

	// Pattern: Just the page number alone (only if page number is in header)
	if pageData.PrintedPage != nil && pageData.HasPageNumberInHeader {
		if plain == *pageData.PrintedPage {
			return true
		}
	}

	return false
}

// JoinPages joins cleaned page texts, handling continuations across page breaks.
// Returns (joinedText, pageBreakPositions).
//
// Continuation detection:
// - Line ends with hyphen: join without space (de-hyphenate)
// - Line ends mid-sentence (no terminal punctuation): join with space
// - Line ends with sentence: join with double newline
func JoinPages(pageTexts []PageText) (string, []int) {
	if len(pageTexts) == 0 {
		return "", nil
	}

	var pageBreaks []int
	var parts []string

	for i, pageText := range pageTexts {
		text := pageText.CleanedText

		if i == 0 {
			parts = append(parts, text)
			continue
		}

		// Record page break
		pageBreaks = append(pageBreaks, pageText.ScanPage)

		prevText := ""
		if len(parts) > 0 {
			prevText = parts[len(parts)-1]
		}

		// Determine how to join
		joinStr := determineJoin(prevText, text)

		if joinStr == "" {
			// Continuation (hyphenation) - modify previous part
			if len(parts) > 0 && strings.HasSuffix(parts[len(parts)-1], "-") {
				parts[len(parts)-1] = strings.TrimSuffix(parts[len(parts)-1], "-")
			}
		}

		parts = append(parts, joinStr+text)
	}

	return strings.Join(parts, ""), pageBreaks
}

// determineJoin determines the join string between two page texts.
func determineJoin(prevText, nextText string) string {
	if prevText == "" {
		return ""
	}

	prevStripped := strings.TrimRightFunc(prevText, unicode.IsSpace)

	if prevStripped == "" {
		return ""
	}

	// Hyphenation: word split across pages
	if strings.HasSuffix(prevStripped, "-") {
		// Check if it's a real hyphenation (lowercase letter before hyphen)
		// Use runes for proper Unicode handling (e.g., accented characters)
		runes := []rune(prevStripped)
		if len(runes) >= 2 && unicode.IsLower(runes[len(runes)-2]) {
			return "" // Join without space, hyphen will be removed
		}
	}

	// Check for sentence ending
	lastChar := prevStripped[len(prevStripped)-1]
	sentenceEnders := ".!?\"'"
	if strings.ContainsRune(sentenceEnders, rune(lastChar)) {
		return "\n\n" // Paragraph break
	}

	// Mid-sentence continuation
	return " "
}

// SplitIntoParagraphs splits text on double newlines into paragraphs.
func SplitIntoParagraphs(text string, startPage int) []*ParagraphState {
	// Split on double newlines
	parts := strings.Split(text, "\n\n")

	var paragraphs []*ParagraphState
	sortOrder := 1

	for _, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}

		paragraphs = append(paragraphs, &ParagraphState{
			SortOrder: sortOrder,
			StartPage: startPage, // Could be refined with page tracking
			RawText:   part,
			WordCount: len(strings.Fields(part)),
		})
		sortOrder++
	}

	return paragraphs
}

// ApplyEdits applies a list of text edits to the text.
// Each edit is applied in sequence, finding the first occurrence of old_text and replacing it.
func ApplyEdits(text string, edits []TextEdit) string {
	for _, edit := range edits {
		if edit.OldText == "" {
			continue
		}
		// Replace first occurrence only
		text = strings.Replace(text, edit.OldText, edit.NewText, 1)
	}
	return text
}
