package toc_finder

import (
	_ "embed"
	"fmt"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for the ToC finder agent.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "agents.toc_finder.system"

// RegisterPrompts registers the toc_finder prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "ToC finder agent system prompt - uses grep and vision to locate Table of Contents",
	})
}

// BuildUserPrompt builds the user prompt for the ToC finder agent.
// This is dynamic and not stored in the database.
func BuildUserPrompt(scanID string, totalPages int, previousAttempt map[string]any) string {
	basePrompt := fmt.Sprintf(`Find the Table of Contents in book: %s

Total pages: %d

Use grep report to identify candidates, then verify with vision + OCR.
Document structure patterns (hierarchy, numbering, visual layout) not content.
Build structure_summary for downstream extraction.`, scanID, totalPages)

	if previousAttempt == nil {
		return basePrompt
	}

	// Include context from previous attempt
	prevReasoning, _ := previousAttempt["reasoning"].(string)
	if prevReasoning == "" {
		prevReasoning = "No reasoning provided"
	}
	prevStrategy, _ := previousAttempt["search_strategy_used"].(string)
	if prevStrategy == "" {
		prevStrategy = "unknown"
	}
	prevPagesChecked, _ := previousAttempt["pages_checked"].(int)
	attemptNum, _ := previousAttempt["attempt_number"].(int)
	if attemptNum == 0 {
		attemptNum = 1
	}

	retryContext := fmt.Sprintf(`

<previous_attempt>
This is ATTEMPT #%d. Previous attempt did not find ToC.

Previous Strategy: %s
Pages Checked: %d
Previous Reasoning: %s
`, attemptNum+1, prevStrategy, prevPagesChecked, prevReasoning)

	// Include previous page observations if available
	if prevStructureNotes, ok := previousAttempt["structure_notes"].(map[string]string); ok && len(prevStructureNotes) > 0 {
		retryContext += "\nPrevious Observations:\n"
		// Sort and limit to first 5 pages
		count := 0
		for pageNum, note := range prevStructureNotes {
			if count >= 5 {
				break
			}
			retryContext += fmt.Sprintf("  Page %s: %s\n", pageNum, note)
			count++
		}
	}

	retryContext += `
Consider:
- Did previous attempt search the right pages?
- Were there false negatives in grep report?
- Should you try different page ranges?
- Could ToC have unusual formatting/naming?
</previous_attempt>
`

	return basePrompt + retryContext
}
