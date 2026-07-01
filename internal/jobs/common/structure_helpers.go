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

	// MaxPolishPromptChars bounds a single polish request while allowing the
	// model to inspect full chapters from normal long-form books. The previous
	// 15k cap hid most OCR errors in long chapters.
	MaxPolishPromptChars = 120000

	maxClassifySnippetChars = 1000
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
     copyright, illustrations lists, table of contents, tabular/list reference appendices,
     orders of battle, rosters, chronology tables, abbreviations, and similar lookup material
   - JUDGMENT: appendix (include only if it is narrative prose that belongs in the listening
     experience; exclude if it is mostly tables, lists, names, citations, abbreviations, or reference data),
     other (use your best judgment based on title and position)

Consider:
- Position in the book (page numbers relative to total pages)
- Title keywords and conventions
- Level/hierarchy (Part vs Chapter vs Section)
- Surrounding context
- Content evidence in the sample text and content_signals field; repeated short lines,
  table/list density, and reference keywords are strong evidence to set audio_include=false

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
- Return at most 50 edits; prefer the highest-confidence OCR fixes
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
		snippet := buildClassifySnippet(ch.MechanicalText)
		signals := classifyContentSignals(ch.MechanicalText, ch.Title)

		pageRange := fmt.Sprintf("pages %d-%d", ch.StartPage, ch.EndPage)
		if ch.EndPage == 0 || ch.EndPage == ch.StartPage {
			pageRange = fmt.Sprintf("page %d", ch.StartPage)
		}

		line := fmt.Sprintf(
			"%d. \"%s\" (%s, level %d %s, word_count %d) [id: %s]\n   content_signals: %s\n   text: %s",
			i+1, ch.Title, pageRange, ch.Level, ch.LevelName, wordCount, ch.EntryID, signals, snippet,
		)
		lines = append(lines, line)
	}

	lines = append(lines, "\nReturn JSON with classifications, content_types, audio_include, and reasoning for each entry.")
	return strings.Join(lines, "\n")
}

func buildClassifySnippet(text string) string {
	text = strings.TrimSpace(text)
	if text == "" {
		return "[no text]"
	}

	var parts []string
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		parts = append(parts, line)
		if len(strings.Join(parts, " | ")) >= maxClassifySnippetChars {
			break
		}
	}
	if len(parts) == 0 {
		return "[no text]"
	}

	snippet := strings.Join(parts, " | ")
	if len(snippet) > maxClassifySnippetChars {
		snippet = snippet[:maxClassifySnippetChars] + "..."
	}
	return snippet
}

func classifyContentSignals(text, title string) string {
	var signals []string
	lower := strings.ToLower(title + "\n" + text)
	for _, keyword := range []string{
		"order of battle",
		"roster",
		"bibliography",
		"glossary",
		"index",
		"abbreviations",
		"chronology",
		"table",
	} {
		if strings.Contains(lower, keyword) {
			signals = append(signals, "keyword:"+keyword)
		}
	}

	var nonEmpty, shortLines, listLike, tableLike int
	for _, line := range strings.Split(text, "\n") {
		line = strings.TrimSpace(line)
		if line == "" {
			continue
		}
		nonEmpty++
		if len(line) <= 48 {
			shortLines++
		}
		if strings.HasPrefix(line, "-") || strings.HasPrefix(line, "*") || looksNumberedListLine(line) {
			listLike++
		}
		if strings.Count(line, "|") >= 2 || strings.Count(line, "\t") >= 2 {
			tableLike++
		}
	}

	if nonEmpty > 0 {
		if shortLines*2 >= nonEmpty {
			signals = append(signals, fmt.Sprintf("many_short_lines:%d/%d", shortLines, nonEmpty))
		}
		if listLike*4 >= nonEmpty {
			signals = append(signals, fmt.Sprintf("list_like_lines:%d/%d", listLike, nonEmpty))
		}
		if tableLike > 0 {
			signals = append(signals, fmt.Sprintf("table_like_lines:%d/%d", tableLike, nonEmpty))
		}
	}

	if len(signals) == 0 {
		return "none"
	}
	return strings.Join(signals, ", ")
}

func looksNumberedListLine(line string) bool {
	if line == "" || !unicode.IsDigit(rune(line[0])) {
		return false
	}
	for _, r := range line[1:] {
		switch {
		case unicode.IsDigit(r):
			continue
		case r == '.' || r == ')' || r == ':':
			return true
		case unicode.IsSpace(r):
			continue
		default:
			return false
		}
	}
	return false
}

// BuildPolishPrompt builds the user prompt for text polishing.
func BuildPolishPrompt(chapter *ChapterState) string {
	text := chapter.MechanicalText
	// Truncate if very long to avoid token limits
	if len(text) > MaxPolishPromptChars {
		text = text[:MaxPolishPromptChars] + "\n\n[... text truncated for length ...]"
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
					"type":     "array",
					"maxItems": 50,
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"old_text": map[string]any{"type": "string", "maxLength": 500},
							"new_text": map[string]any{"type": "string", "maxLength": 500},
							"reason":   map[string]any{"type": "string", "maxLength": 200},
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
