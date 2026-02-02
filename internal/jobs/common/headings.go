package common

import (
	"regexp"
	"strings"
)

// HeadingItem represents a markdown heading extracted from page content.
type HeadingItem struct {
	Level      int    `json:"level"`
	Text       string `json:"text"`
	LineNumber int    `json:"line_number"`
}

// headingPattern matches markdown headings (# through ######).
var headingPattern = regexp.MustCompile(`^(#{1,6})\s+(.+)$`)

// alphanumPattern checks if text contains at least one alphanumeric character.
var alphanumPattern = regexp.MustCompile(`[a-zA-Z0-9]`)

// ExtractHeadings extracts markdown headings from text.
// Returns a slice of HeadingItem for each heading found.
func ExtractHeadings(markdown string) []HeadingItem {
	var headings []HeadingItem
	for lineNum, line := range strings.Split(markdown, "\n") {
		match := headingPattern.FindStringSubmatch(strings.TrimSpace(line))
		if match == nil {
			continue
		}
		text := strings.TrimSpace(match[2])
		// Only include headings with actual alphanumeric content
		if alphanumPattern.MatchString(text) {
			headings = append(headings, HeadingItem{
				Level:      len(match[1]),
				Text:       text,
				LineNumber: lineNum + 1, // 1-indexed
			})
		}
	}
	return headings
}
