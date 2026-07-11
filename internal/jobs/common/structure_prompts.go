package common

import (
	"fmt"
)

// Structure prompt keys.
const (
	PromptKeyClassifySystem = "stages.common_structure.classify.system"
	PromptKeyPolishSystem   = "stages.common_structure.polish.system"

	// MaxPolishPromptChars bounds a single polish request while allowing the
	// model to inspect full chapters from normal long-form books. The previous
	// 15k cap hid most OCR errors in long chapters.
	MaxPolishPromptChars = 120000

	// MaxPolishOutputTokens accommodates the strict 50-edit response schema.
	// Scholarly chapters with dense OCR damage can legitimately exceed the
	// generic 4K allowance; truncated edit JSON must still fail closed.
	MaxPolishOutputTokens = 16384

	// Classification emits four compact entry-keyed maps. Scale the allowance
	// for unusually granular ToCs while keeping normal books from requesting an
	// effectively unbounded structured completion.
	minClassifyOutputTokens = 4096
	maxClassifyOutputTokens = 32768
	classifyTokensPerEntry  = 96

	maxClassifySnippetChars = 1000
)

// ClassifyMaxOutputTokens returns a bounded output allowance sized to the
// number of entries being classified.
func ClassifyMaxOutputTokens(entryCount int) int {
	tokens := entryCount * classifyTokensPerEntry
	if tokens < minClassifyOutputTokens {
		return minClassifyOutputTokens
	}
	if tokens > maxClassifyOutputTokens {
		return maxClassifyOutputTokens
	}
	return tokens
}

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
- Return compact JSON with no indentation or repeated whitespace
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
