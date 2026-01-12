package toc_entry_finder

import (
	_ "embed"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for the ToC entry finder agent.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "agents.toc_entry_finder.system"

// UserPromptKey is the hierarchical key for the user prompt template.
const UserPromptKey = "agents.toc_entry_finder.user"

//go:embed user.tmpl
var userPromptTemplate string

// RegisterPrompts registers the toc_entry_finder prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "ToC entry finder agent system prompt - locates where ToC entries appear in scanned books",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTemplate,
		Description: "ToC entry finder agent user prompt template - provides entry details and book context",
	})
}

// BookStructure provides context about the book's layout.
type BookStructure struct {
	TotalPages       int    `json:"total_pages"`
	BackMatterStart  int    `json:"back_matter_start"`   // Estimated start of back matter
	BackMatterTypes  string `json:"back_matter_types"`   // e.g., "footnotes, bibliography, index"
}

// BuildUserPrompt builds the user prompt for finding a specific ToC entry.
func BuildUserPrompt(entry *TocEntry, totalPages int, bookStructure *BookStructure) string {
	// Build search term: "chapter 5 The Beginning"
	searchParts := []string{}
	if entry.LevelName != "" {
		searchParts = append(searchParts, entry.LevelName)
	} else if entry.Level > 0 {
		searchParts = append(searchParts, fmt.Sprintf("level %d", entry.Level))
	}
	if entry.EntryNumber != "" {
		searchParts = append(searchParts, entry.EntryNumber)
	}
	if entry.Title != "" {
		searchParts = append(searchParts, entry.Title)
	}
	searchTerm := strings.Join(searchParts, " ")

	prompt := fmt.Sprintf(`Find: "%s"`, searchTerm)

	if entry.PrintedPageNumber != "" {
		prompt += fmt.Sprintf(" (printed page %s, but use scan pages)", entry.PrintedPageNumber)
	}

	prompt += fmt.Sprintf(" [%d pages in book]", totalPages)

	// Add book structure context
	if bookStructure != nil && bookStructure.BackMatterStart > 0 {
		prompt += fmt.Sprintf("\n\nBOOK STRUCTURE: Back matter (including %s) starts around page %d. Results from pages %d+ are likely footnote references, not chapter starts.",
			bookStructure.BackMatterTypes, bookStructure.BackMatterStart, bookStructure.BackMatterStart)
	}

	return prompt
}
