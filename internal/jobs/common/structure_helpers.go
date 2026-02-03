package common

import (
	"fmt"
	"strings"
	"unicode"
)

// Structure prompt keys.
const (
	PromptKeyClassifySystem = "stages.common_structure.classify.system"
	PromptKeyPolishSystem   = "stages.common_structure.polish.system"
)

// ClassifySystemPrompt is the system prompt for content classification.
const ClassifySystemPrompt = `You are a book structure analyzer preparing a book for audiobook output.
Given a list of table of contents entries, for each entry:

1. Assign a granular content_type:
   - body, preface, foreword, introduction, prologue, epilogue, afterword,
     author_note, dedication, appendix, index, bibliography, glossary,
     notes, endnotes, acknowledgments, about_author, copyright,
     illustrations_list, other

2. Assign matter_type (structural grouping): front_matter, body, back_matter

3. Decide audio_include (true/false): whether this content should be read aloud
   - INCLUDE: body content, preface, foreword, introduction, prologue, epilogue,
     afterword, author's note, dedication, acknowledgments, about the author
   - EXCLUDE: index, bibliography, references, glossary, notes/endnotes,
     copyright, illustrations lists, table of contents
   - JUDGMENT: appendix (include if narrative/short, exclude if tabular/reference),
     other (use your best judgment based on title and position)

Consider:
- Position in the book (page numbers relative to total pages)
- Title keywords and conventions
- Level/hierarchy (Part vs Chapter vs Section)
- Surrounding context

Return a JSON object with:
- "classifications": entry_id -> matter_type
- "content_types": entry_id -> content_type
- "audio_include": entry_id -> boolean
- "reasoning": entry_id -> short explanation (focus on audio_include decision)`

// PolishSystemPrompt is the system prompt for text polishing.
const PolishSystemPrompt = `You are a text editor cleaning up OCR output from a scanned book.

Your job is to identify and fix issues in the text, returning a list of specific edits.

Common issues to fix:
1. OCR artifacts (stray characters, garbled text)
2. Page-break join issues (words split incorrectly, missing spaces)
3. Hyphenation artifacts (de-hyphenate words split across pages)
4. Inconsistent formatting (normalize markdown headers, lists)
5. Image caption remnants that don't belong in flowing text
6. Repeated headers/footers that weren't fully removed

Rules:
- ONLY return edits for actual problems
- Keep edits minimal and precise
- NEVER change the meaning or content
- NEVER rewrite sentences for style
- Preserve all substantive text
- If text looks fine, return empty edits list

Return JSON with this exact structure:
{
  "edits": [
    {
      "old_text": "exact text to find",
      "new_text": "replacement text",
      "reason": "brief explanation"
    }
  ]
}`

// PageText holds text from a single page.
type PageText struct {
	ScanPage    int
	PrintedPage *string
	RawText     string
	CleanedText string
}

// TextEdit represents an edit from LLM polish.
type TextEdit struct {
	OldText string `json:"old_text"`
	NewText string `json:"new_text"`
	Reason  string `json:"reason"`
}

// ClassifyResult represents the LLM classification response.
type ClassifyResult struct {
	Classifications map[string]string `json:"classifications"`
	ContentTypes    map[string]string `json:"content_types"`
	AudioInclude    map[string]bool   `json:"audio_include"`
	Reasoning       map[string]string `json:"reasoning"`
}

// PolishResult represents the LLM polish response.
type PolishResult struct {
	Edits []TextEdit `json:"edits"`
}

// BuildClassifyPrompt builds the user prompt for content classification.
func BuildClassifyPrompt(chapters []*ChapterState, totalPages int) string {
	var lines []string
	lines = append(lines, fmt.Sprintf("Total pages in book: %d", totalPages))
	lines = append(lines, "Classify each entry with content_type, matter_type, and audio_include:\n")

	for i, ch := range chapters {
		wordCount := ch.WordCount
		if wordCount == 0 && ch.MechanicalText != "" {
			wordCount = CountWords(ch.MechanicalText)
		}
		snippet := strings.TrimSpace(ch.MechanicalText)
		if snippet == "" {
			snippet = "[no text]"
		} else {
			snippet = strings.ReplaceAll(snippet, "\n", " ")
			if len(snippet) > 200 {
				snippet = snippet[:200] + "..."
			}
		}

		pageRange := fmt.Sprintf("pages %d-%d", ch.StartPage, ch.EndPage)
		if ch.EndPage == 0 || ch.EndPage == ch.StartPage {
			pageRange = fmt.Sprintf("page %d", ch.StartPage)
		}

		line := fmt.Sprintf(
			"%d. \"%s\" (%s, level %d %s, word_count %d) [id: %s]\n   text: %s",
			i+1, ch.Title, pageRange, ch.Level, ch.LevelName, wordCount, ch.EntryID, snippet,
		)
		lines = append(lines, line)
	}

	lines = append(lines, "\nReturn JSON with classifications, content_types, audio_include, and reasoning for each entry.")
	return strings.Join(lines, "\n")
}

// BuildPolishPrompt builds the user prompt for text polishing.
func BuildPolishPrompt(chapter *ChapterState) string {
	text := chapter.MechanicalText
	// Truncate if very long to avoid token limits
	maxChars := 15000
	if len(text) > maxChars {
		text = text[:maxChars] + "\n\n[... text truncated for length ...]"
	}

	return fmt.Sprintf(`Section: "%s"

Text to review:
---
%s
---

Analyze this text and return a JSON list of edits to fix any OCR or formatting issues.
If the text looks clean, return {"edits": []}.`, chapter.Title, text)
}

// ClassifyJSONSchema returns the JSON schema for matter classification.
func ClassifyJSONSchema() map[string]any {
	return map[string]any{
		"name":   "entry_classifications",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"classifications": map[string]any{
					"type": "object",
					"additionalProperties": map[string]any{
						"type": "string",
						"enum": []string{"front_matter", "body", "back_matter"},
					},
				},
				"content_types": map[string]any{
					"type": "object",
					"additionalProperties": map[string]any{
						"type": "string",
						"enum": []string{
							"body",
							"preface",
							"foreword",
							"introduction",
							"prologue",
							"epilogue",
							"afterword",
							"author_note",
							"dedication",
							"appendix",
							"index",
							"bibliography",
							"glossary",
							"notes",
							"endnotes",
							"acknowledgments",
							"about_author",
							"copyright",
							"illustrations_list",
							"other",
						},
					},
				},
				"audio_include": map[string]any{
					"type": "object",
					"additionalProperties": map[string]any{
						"type": "boolean",
					},
				},
				"reasoning": map[string]any{
					"type": "object",
					"additionalProperties": map[string]any{
						"type": "string",
					},
				},
			},
			"required":             []string{"classifications", "content_types", "audio_include", "reasoning"},
			"additionalProperties": false,
		},
	}
}

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

// PolishJSONSchema returns the JSON schema for text polishing.
func PolishJSONSchema() map[string]any {
	return map[string]any{
		"name":   "text_edits",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"edits": map[string]any{
					"type": "array",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"old_text": map[string]any{"type": "string"},
							"new_text": map[string]any{"type": "string"},
							"reason":   map[string]any{"type": "string"},
						},
						"required":             []string{"old_text", "new_text", "reason"},
						"additionalProperties": false,
					},
				},
			},
			"required":             []string{"edits"},
			"additionalProperties": false,
		},
	}
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
