package extract_toc

import (
	_ "embed"
	"fmt"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for ToC extraction.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "stages.extract_toc.system"

// RegisterPrompts registers the extract_toc prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "ToC extraction system prompt - extracts structured entries from ToC pages",
	})
}

// ToCPage represents a single page of ToC content for extraction.
type ToCPage struct {
	PageNum int    `json:"page_num"`
	OCRText string `json:"ocr_text"`
}

// BuildUserPrompt builds the user prompt for ToC extraction.
// This is dynamic and not stored in the database.
func BuildUserPrompt(tocPages []ToCPage, structureSummary *StructureSummary) string {
	// Build complete OCR text with page markers
	completeText := ""
	for _, page := range tocPages {
		completeText += fmt.Sprintf("\n%s\n", "================================================================================")
		completeText += fmt.Sprintf("PAGE %d of %d\n", page.PageNum, len(tocPages))
		completeText += fmt.Sprintf("%s\n", "================================================================================")
		completeText += page.OCRText
		completeText += "\n"
	}

	prompt := fmt.Sprintf(`<task>
Extract ALL Table of Contents entries from these %d pages.

Return a complete, ordered list of entries from top to bottom.
</task>

<complete_toc>
%s
</complete_toc>
`, len(tocPages), completeText)

	if structureSummary != nil {
		prompt += fmt.Sprintf(`
<global_structure>
The find phase identified this ToC structure:

Total levels: %d
`, structureSummary.TotalLevels)

		for level, pattern := range structureSummary.LevelPatterns {
			numbering := "None"
			if pattern.Numbering != nil {
				numbering = *pattern.Numbering
			}
			semanticType := "null"
			if pattern.SemanticType != nil {
				semanticType = *pattern.SemanticType
			}
			prompt += fmt.Sprintf(`
Level %s:
  - Visual: %s
  - Numbering: %s
  - Has page numbers: %v
  - Semantic type: %s
`, level, pattern.Visual, numbering, pattern.HasPageNumbers, semanticType)
		}

		prompt += `
Use semantic_type from each level as the level_name for entries.
Override only if entry text clearly indicates different type (e.g., "Appendix A").
</global_structure>
`
	}

	prompt += `
<extraction_guidelines>

**TITLE EXTRACTION** (most important!):
- ALWAYS strip prefixes from titles
- "Chapter 5: The War Years" → title="The War Years", entry_number="5"
- "Prologue: City on Fire" → title="City on Fire", level_name="prologue"
- "Part III: The End" → title="The End", entry_number="III"
- Empty titles are valid: "Part I" → title="", entry_number="I"

**MULTI-LINE TITLES**:
When a title spans multiple lines at the SAME indentation, merge them:
` + "```" + `
Experiments in Happiness:
Life and Love in New Culture China
` + "```" + `
This is ONE entry: title="Experiments in Happiness: Life and Love in New Culture China"

**HIERARCHY FROM INDENTATION**:
- Level 1: Flush left (no indent)
- Level 2: Moderate indent (typically 2-4 spaces or visual indent)
- Level 3: Deep indent (further indented under Level 2)

Parent entries (like "Part I") typically have no page numbers.

**STANDALONE MARKERS vs MERGED TITLES**:
- "PART I" + indented chapters below → PART I is separate entry (level 1)
- "Part One" + "The Path to War" at same indent → merge into one entry

**PAGE NUMBERS**:
- Extract from right side: "15", "ix", "xiii", "253"
- null if no page number present

**BACK MATTER**:
Notes, Bibliography, Index, Appendices → always Level 1

</extraction_guidelines>

<output_format>
Return a JSON array with ALL entries in order:
{
  "entries": [
    {
      "entry_number": "I" or null,
      "title": "text without prefix",
      "level": 1,
      "level_name": "part",
      "printed_page_number": "3" or null
    },
    ...
  ]
}
</output_format>

Extract ALL entries in top-to-bottom order. Be thorough.`

	return prompt
}
