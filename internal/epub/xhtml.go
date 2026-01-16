package epub

import (
	"fmt"
	"regexp"
	"strings"
)

// generateChapterXHTML converts a chapter's polished text to XHTML.
func (b *Builder) generateChapterXHTML(ch Chapter) string {
	var sb strings.Builder

	// XHTML header
	sb.WriteString(`<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head>
  <title>`)
	sb.WriteString(escapeXML(ch.Title))
	sb.WriteString(`</title>
  <link rel="stylesheet" type="text/css" href="../styles/style.css"/>
</head>
<body`)

	// Add class based on matter type
	switch ch.MatterType {
	case "front_matter":
		sb.WriteString(` class="front-matter"`)
	case "back_matter":
		sb.WriteString(` class="back-matter"`)
		if ch.LevelName == "notes" {
			sb.WriteString(` class="back-matter notes"`)
		}
	}
	sb.WriteString(">\n")

	// Convert markdown to XHTML
	content := markdownToXHTML(ch.PolishedText, ch)
	sb.WriteString(content)

	sb.WriteString("\n</body>\n</html>\n")

	return sb.String()
}

// markdownToXHTML converts markdown-formatted text to XHTML.
// This is a simple converter that handles the common cases from polished text.
func markdownToXHTML(md string, ch Chapter) string {
	return markdownToXHTMLWithIDs(md, ch, false)
}

// markdownToXHTMLWithIDs converts markdown to XHTML with optional paragraph IDs for Media Overlays.
// When withIDs is true, paragraphs get id="p0", id="p1", etc. for SMIL references.
func markdownToXHTMLWithIDs(md string, ch Chapter, withIDs bool) string {
	if md == "" {
		return fmt.Sprintf("<h1>%s</h1>\n", escapeXML(ch.Title))
	}

	lines := strings.Split(md, "\n")
	var result strings.Builder
	var inParagraph bool
	paragraphIdx := 0

	for i, line := range lines {
		trimmed := strings.TrimSpace(line)

		// Empty line closes paragraph
		if trimmed == "" {
			if inParagraph {
				result.WriteString("</p>\n")
				inParagraph = false
			}
			continue
		}

		// Headers
		if strings.HasPrefix(trimmed, "# ") {
			if inParagraph {
				result.WriteString("</p>\n")
				inParagraph = false
			}
			result.WriteString("<h1>")
			result.WriteString(escapeXML(strings.TrimPrefix(trimmed, "# ")))
			result.WriteString("</h1>\n")
			continue
		}
		if strings.HasPrefix(trimmed, "## ") {
			if inParagraph {
				result.WriteString("</p>\n")
				inParagraph = false
			}
			result.WriteString("<h2>")
			result.WriteString(escapeXML(strings.TrimPrefix(trimmed, "## ")))
			result.WriteString("</h2>\n")
			continue
		}
		if strings.HasPrefix(trimmed, "### ") {
			if inParagraph {
				result.WriteString("</p>\n")
				inParagraph = false
			}
			result.WriteString("<h3>")
			result.WriteString(escapeXML(strings.TrimPrefix(trimmed, "### ")))
			result.WriteString("</h3>\n")
			continue
		}

		// Blockquote
		if strings.HasPrefix(trimmed, "> ") {
			if inParagraph {
				result.WriteString("</p>\n")
				inParagraph = false
			}
			if withIDs {
				result.WriteString(fmt.Sprintf("<blockquote><p id=\"p%d\">", paragraphIdx))
				paragraphIdx++
			} else {
				result.WriteString("<blockquote><p>")
			}
			result.WriteString(processInlineFormatting(strings.TrimPrefix(trimmed, "> ")))
			result.WriteString("</p></blockquote>\n")
			continue
		}

		// Horizontal rule
		if trimmed == "---" || trimmed == "***" || trimmed == "___" {
			if inParagraph {
				result.WriteString("</p>\n")
				inParagraph = false
			}
			result.WriteString("<hr/>\n")
			continue
		}

		// Regular paragraph text
		if !inParagraph {
			if withIDs {
				result.WriteString(fmt.Sprintf("<p id=\"p%d\">", paragraphIdx))
				paragraphIdx++
			} else {
				result.WriteString("<p>")
			}
			inParagraph = true
		} else {
			// Check if this looks like a new paragraph (starts with capital after sentence end)
			// or continuation of current paragraph
			if i > 0 && shouldStartNewParagraph(lines[i-1], trimmed) {
				if withIDs {
					result.WriteString(fmt.Sprintf("</p>\n<p id=\"p%d\">", paragraphIdx))
					paragraphIdx++
				} else {
					result.WriteString("</p>\n<p>")
				}
			} else {
				result.WriteString(" ")
			}
		}
		result.WriteString(processInlineFormatting(trimmed))
	}

	// Close any open paragraph
	if inParagraph {
		result.WriteString("</p>\n")
	}

	return result.String()
}

// shouldStartNewParagraph determines if a new line should start a new paragraph.
func shouldStartNewParagraph(prevLine, currentLine string) bool {
	prevTrimmed := strings.TrimSpace(prevLine)
	if prevTrimmed == "" {
		return true
	}
	// Previous line ends with sentence-ending punctuation and current starts with capital
	if len(currentLine) > 0 {
		lastChar := prevTrimmed[len(prevTrimmed)-1]
		firstChar := currentLine[0]
		if (lastChar == '.' || lastChar == '!' || lastChar == '?') &&
			firstChar >= 'A' && firstChar <= 'Z' {
			// Could be new paragraph, but often just continuation
			// Be conservative - only split on double newline (handled elsewhere)
			return false
		}
	}
	return false
}

// processInlineFormatting handles bold, italic, and other inline markdown.
func processInlineFormatting(text string) string {
	// Escape XML first
	text = escapeXML(text)

	// Bold: **text** or __text__
	boldRe := regexp.MustCompile(`\*\*(.+?)\*\*|__(.+?)__`)
	text = boldRe.ReplaceAllStringFunc(text, func(match string) string {
		inner := strings.Trim(match, "*_")
		return "<strong>" + inner + "</strong>"
	})

	// Italic: *text* or _text_
	italicRe := regexp.MustCompile(`\*([^*]+)\*|_([^_]+)_`)
	text = italicRe.ReplaceAllStringFunc(text, func(match string) string {
		inner := strings.Trim(match, "*_")
		return "<em>" + inner + "</em>"
	})

	return text
}
