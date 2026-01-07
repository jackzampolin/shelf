package gap_investigator

import (
	_ "embed"
	"fmt"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for the gap investigator agent.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "agents.gap_investigator.system"

// RegisterPrompts registers the gap_investigator prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "Gap investigator agent system prompt - investigates page coverage gaps",
	})
}

// GapInfo describes a gap in page coverage.
type GapInfo struct {
	Key            string
	StartPage      int
	EndPage        int
	Size           int
	PrevEntryTitle string
	PrevEntryPage  int
	NextEntryTitle string
	NextEntryPage  int
}

// LinkedEntry represents a ToC entry for context.
type LinkedEntry struct {
	DocID      string
	Title      string
	Level      int
	LevelName  string
	ActualPage int
}

// BuildUserPrompt builds the user prompt for investigating a gap.
func BuildUserPrompt(gap *GapInfo, bodyStart, bodyEnd, totalPages int) string {
	// Calculate relative position
	bodySize := bodyEnd - bodyStart + 1
	gapPosition := float64(gap.StartPage-bodyStart) / float64(bodySize) * 100

	positionHint := ""
	if gapPosition < 10 {
		positionHint = "This gap is near the BEGINNING of the body - possibly introduction/prologue area."
	} else if gapPosition > 90 {
		positionHint = "This gap is near the END of the body - possibly conclusion/appendix area."
	} else {
		positionHint = fmt.Sprintf("This gap is around %.0f%% through the body.", gapPosition)
	}

	prompt := fmt.Sprintf(`## Gap Investigation

**Gap location:** Pages %d to %d (%d pages)
**Body range:** Pages %d to %d
%s
`, gap.StartPage, gap.EndPage, gap.Size, bodyStart, bodyEnd, positionHint)

	if gap.PrevEntryTitle != "" {
		prompt += fmt.Sprintf("\n- Entry BEFORE gap: \"%s\" at page %d", gap.PrevEntryTitle, gap.PrevEntryPage)
	}
	if gap.NextEntryTitle != "" {
		prompt += fmt.Sprintf("\n- Entry AFTER gap: \"%s\" at page %d", gap.NextEntryTitle, gap.NextEntryPage)
	}

	prompt += `

## Your Task
1. Call get_gap_context() to understand the situation
2. Investigate using page images and OCR
3. Determine the cause and apply the appropriate fix

Start by getting the gap context.`

	return prompt
}

// Result represents the agent's fix recommendation.
type Result struct {
	FixType    string `json:"fix_type"`     // "add_entry", "correct_entry", "no_fix_needed", "flag_for_review"
	ScanPage   int    `json:"scan_page"`    // For add_entry
	Title      string `json:"title"`        // For add_entry
	Level      int    `json:"level"`        // For add_entry
	LevelName  string `json:"level_name"`   // For add_entry
	EntryDocID string `json:"entry_doc_id"` // For correct_entry
	Reasoning  string `json:"reasoning"`
	Flagged    bool   `json:"flagged"`
}
