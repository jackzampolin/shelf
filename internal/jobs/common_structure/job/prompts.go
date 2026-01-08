package job

import (
	"fmt"
	"strings"
)

// Prompt keys for common-structure job.
const (
	PromptKeyClassifySystem = "stages.common_structure.classify.system"
	PromptKeyPolishSystem   = "stages.common_structure.polish.system"
)

// PromptKeys returns the list of prompt keys used by this job.
func PromptKeys() []string {
	return []string{
		PromptKeyClassifySystem,
		PromptKeyPolishSystem,
	}
}

// ClassifySystemPrompt is the system prompt for matter classification.
const ClassifySystemPrompt = `You are a book structure analyzer. Given a list of table of contents entries from a book, classify each entry into one of three categories:

- **front_matter**: Content that appears before the main text. Examples: preface, foreword, introduction, prologue, timeline, list of characters, maps, author's note (when at start).

- **body**: The main content of the book. Examples: chapters, parts, acts, sections with numbers or dates as titles.

- **back_matter**: Content that appears after the main text. Examples: epilogue, afterword, appendix, notes, endnotes, bibliography, references, glossary, index, acknowledgments, about the author, also by author.

Consider:
1. Position in the book (early entries more likely front matter, late entries more likely back matter)
2. Title keywords and conventions
3. Surrounding context (a "Notes" section after chapters is back matter)

Return a JSON object with:
- "classifications": entry_id -> category mapping
- "reasoning": entry_id -> brief explanation of why that category was chosen`

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

// BuildClassifyPrompt builds the user prompt for matter classification.
func BuildClassifyPrompt(chapters []*ChapterState) string {
	var lines []string
	lines = append(lines, "Classify each entry as front_matter, body, or back_matter:\n")

	for i, ch := range chapters {
		line := fmt.Sprintf("%d. \"%s\" (page %d) [id: %s]",
			i+1, ch.Title, ch.StartPage, ch.EntryID)
		lines = append(lines, line)
	}

	lines = append(lines, "\nReturn JSON with classifications and reasoning for each entry.")
	return strings.Join(lines, "\n")
}

// BuildPolishPrompt builds the user prompt for text polishing.
func BuildPolishPrompt(sectionTitle string, text string) string {
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
If the text looks clean, return {"edits": []}.`, sectionTitle, text)
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
				"reasoning": map[string]any{
					"type": "object",
					"additionalProperties": map[string]any{
						"type": "string",
					},
				},
			},
			"required":             []string{"classifications", "reasoning"},
			"additionalProperties": false,
		},
	}
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

// GetEmbeddedDefault returns the embedded default prompt for a key.
func GetEmbeddedDefault(key string) string {
	switch key {
	case PromptKeyClassifySystem:
		return ClassifySystemPrompt
	case PromptKeyPolishSystem:
		return PolishSystemPrompt
	default:
		return ""
	}
}
