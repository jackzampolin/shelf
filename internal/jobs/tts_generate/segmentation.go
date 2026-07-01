package tts_generate

import (
	"strings"
)

// splitIntoParagraphs splits text into paragraphs.
// Paragraphs are separated by double newlines or significant whitespace.
func splitIntoParagraphs(text string) []string {
	// Normalize line endings
	text = strings.ReplaceAll(text, "\r\n", "\n")
	text = strings.ReplaceAll(text, "\r", "\n")

	// Split on double newlines (paragraph breaks)
	rawParagraphs := strings.Split(text, "\n\n")

	var paragraphs []string
	for _, p := range rawParagraphs {
		// Trim whitespace and normalize internal whitespace
		p = strings.TrimSpace(p)
		if p == "" {
			continue
		}

		// Replace single newlines with spaces (within a paragraph)
		p = strings.ReplaceAll(p, "\n", " ")

		// Collapse multiple spaces
		for strings.Contains(p, "  ") {
			p = strings.ReplaceAll(p, "  ", " ")
		}

		paragraphs = append(paragraphs, p)
	}

	return paragraphs
}
