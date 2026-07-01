package common

import (
	"strings"
	"unicode"
)

// StripHeaderFooter removes exact running header/footer lines from OCR text.
func StripHeaderFooter(text, header, footer string) string {
	if text == "" {
		return text
	}
	headerNorm := normalizeLine(header)
	footerNorm := normalizeLine(footer)
	if headerNorm == "" && footerNorm == "" {
		return text
	}

	lines := strings.Split(text, "\n")
	cleaned := make([]string, 0, len(lines))
	for _, line := range lines {
		norm := normalizeLine(line)
		if headerNorm != "" && norm == headerNorm {
			continue
		}
		if footerNorm != "" && norm == footerNorm {
			continue
		}
		cleaned = append(cleaned, line)
	}
	return strings.Join(cleaned, "\n")
}

func normalizeLine(line string) string {
	trimmed := strings.TrimSpace(line)
	if trimmed == "" {
		return ""
	}
	parts := strings.Fields(strings.ToLower(trimmed))
	return strings.Join(parts, " ")
}

// MergeChapterPages joins page texts into a single chapter text.
func MergeChapterPages(pageTexts []PageText) string {
	if len(pageTexts) == 0 {
		return ""
	}

	var parts []string
	for i, pageText := range pageTexts {
		text := pageText.CleanedText
		if text == "" {
			text = pageText.RawText
		}

		if i == 0 {
			parts = append(parts, text)
			continue
		}

		prevText := ""
		if len(parts) > 0 {
			prevText = parts[len(parts)-1]
		}

		// Determine how to join
		joinStr := determineJoin(prevText, text)

		if joinStr == "" && len(parts) > 0 && strings.HasSuffix(parts[len(parts)-1], "-") {
			// Dehyphenation
			parts[len(parts)-1] = strings.TrimSuffix(parts[len(parts)-1], "-")
		}

		parts = append(parts, joinStr+text)
	}

	return strings.Join(parts, "")
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

// CleanPageText removes running headers and page numbers from page text.
func CleanPageText(text string) string {
	lines := strings.Split(text, "\n")
	if len(lines) == 0 {
		return text
	}

	// Remove first few lines that look like headers (short lines at the start)
	var cleanedLines []string
	headerRemoved := false

	for i, line := range lines {
		// Only check first 3 lines for potential headers
		if i < 3 && !headerRemoved {
			stripped := strings.TrimSpace(line)
			// Skip short lines that might be headers/page numbers
			if len(stripped) < 50 && (strings.Contains(stripped, "/") || isPageNumberLine(stripped)) {
				headerRemoved = true
				continue
			}
		}
		cleanedLines = append(cleanedLines, line)
	}

	return strings.TrimSpace(strings.Join(cleanedLines, "\n"))
}

// isPageNumberLine checks if a line looks like a page number.
func isPageNumberLine(line string) bool {
	stripped := strings.TrimSpace(line)
	if stripped == "" {
		return false
	}

	// Remove markdown formatting
	plain := strings.ReplaceAll(stripped, "**", "")
	plain = strings.ReplaceAll(plain, "*", "")
	plain = strings.TrimSpace(plain)

	// Check if it's just a number
	for _, r := range plain {
		if !unicode.IsDigit(r) {
			return false
		}
	}
	return len(plain) > 0 && len(plain) < 5
}

// CountWords counts the number of words in text.
func CountWords(text string) int {
	return len(strings.Fields(text))
}

// ApplyEdits applies a list of text edits to the text.
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
