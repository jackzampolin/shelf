package toc_finder

import (
	"bytes"
	_ "embed"
	"text/template"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

//go:embed user.tmpl
var userPromptTmpl string

var userTemplate = template.Must(template.New("user").Parse(userPromptTmpl))

// SystemPrompt returns the system prompt for the ToC finder agent.
func SystemPrompt() string {
	return systemPrompt
}

// Prompt keys
const (
	SystemPromptKey = "agents.toc_finder.system"
	UserPromptKey   = "agents.toc_finder.user"
)

// PromptKey is the hierarchical key for this prompt (alias for SystemPromptKey).
// Deprecated: Use SystemPromptKey instead.
const PromptKey = SystemPromptKey

// RegisterPrompts registers the toc_finder prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemPromptKey,
		Text:        systemPrompt,
		Description: "ToC finder agent system prompt - uses grep and vision to locate Table of Contents",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTmpl,
		Description: "ToC finder agent user prompt template - provides book info and retry context",
	})
}

// PreviousAttemptData contains data about a previous failed ToC finding attempt.
type PreviousAttemptData struct {
	AttemptNumber  int
	Strategy       string
	PagesChecked   int
	Reasoning      string
	StructureNotes map[string]string
}

// UserPromptData contains the data needed to render the user prompt template.
type UserPromptData struct {
	ScanID          string
	TotalPages      int
	PreviousAttempt *PreviousAttemptData
}

// UserPrompt renders the user prompt template with the given data.
func UserPrompt(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userTemplate.Execute(&buf, data); err != nil {
		// Fallback to raw template on error
		return userPromptTmpl
	}
	return buf.String()
}

// UserPromptWithOverride renders a user prompt, using an override template if provided.
func UserPromptWithOverride(data UserPromptData, override string) string {
	if override == "" {
		return UserPrompt(data)
	}
	// Parse and execute the override template
	tmpl, err := template.New("override").Parse(override)
	if err != nil {
		return UserPrompt(data) // Fallback to default on parse error
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return UserPrompt(data) // Fallback to default on execute error
	}
	return buf.String()
}

// BuildUserPrompt builds the user prompt for the ToC finder agent.
// Deprecated: Use UserPrompt(UserPromptData) instead.
func BuildUserPrompt(scanID string, totalPages int, previousAttempt map[string]any) string {
	data := UserPromptData{
		ScanID:     scanID,
		TotalPages: totalPages,
	}

	if previousAttempt != nil {
		// Extract data from the map
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

		var structureNotes map[string]string
		if notes, ok := previousAttempt["structure_notes"].(map[string]string); ok {
			// Limit to first 5 notes
			structureNotes = make(map[string]string)
			count := 0
			for k, v := range notes {
				if count >= 5 {
					break
				}
				structureNotes[k] = v
				count++
			}
		}

		data.PreviousAttempt = &PreviousAttemptData{
			AttemptNumber:  attemptNum + 1, // Next attempt number
			Strategy:       prevStrategy,
			PagesChecked:   prevPagesChecked,
			Reasoning:      prevReasoning,
			StructureNotes: structureNotes,
		}
	}

	return UserPrompt(data)
}
