package chapter_finder

import (
	_ "embed"
	"fmt"
	"strings"
	"unicode"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for the chapter finder agent.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "agents.chapter_finder.system"

// RegisterPrompts registers the chapter_finder prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "Chapter finder agent system prompt - discovers chapters not in ToC",
	})
}

// EntryToFind describes the chapter entry to search for.
type EntryToFind struct {
	LevelName        string // "chapter", "part", "section"
	Identifier       string // "14", "III", "A"
	HeadingFormat    string // "Chapter {n}", "{n}", "CHAPTER {n}"
	ExpectedNearPage int    // Estimated page based on sequence
	SearchRangeStart int
	SearchRangeEnd   int
}

// ExcludedRange represents a page range to skip.
type ExcludedRange struct {
	StartPage int
	EndPage   int
	Reason    string
}

// BuildUserPrompt builds the user prompt for finding a specific entry.
func BuildUserPrompt(entry *EntryToFind, totalPages int, excludedRanges []ExcludedRange) string {
	// Build search term from heading_format
	var searchTerm string
	if entry.HeadingFormat != "" {
		searchTerm = strings.ReplaceAll(entry.HeadingFormat, "{n}", entry.Identifier)
	} else if entry.LevelName != "" {
		searchTerm = fmt.Sprintf("%s %s", titleCase(entry.LevelName), entry.Identifier)
	} else {
		searchTerm = entry.Identifier
	}

	prompt := fmt.Sprintf("Find: %s", searchTerm)

	if entry.HeadingFormat != "" {
		prompt += fmt.Sprintf("\nHeading format: %q (search for variations)", entry.HeadingFormat)
	}

	prompt += fmt.Sprintf("\nExpected location: around page %d (search pages %d-%d first)",
		entry.ExpectedNearPage, entry.SearchRangeStart, entry.SearchRangeEnd)

	prompt += fmt.Sprintf("\nBook has %d total pages.", totalPages)

	// Add excluded ranges
	if len(excludedRanges) > 0 {
		prompt += "\n\nEXCLUDED RANGES (skip matches in these pages - they're back matter):"
		for _, ex := range excludedRanges {
			prompt += fmt.Sprintf("\n  - Pages %d-%d: %s", ex.StartPage, ex.EndPage, ex.Reason)
		}
	}

	prompt += "\n\nTIP: If heading_format is \"{n}\", search for just the number (e.g., \"14\", \"# 14\")."

	return prompt
}

// Result represents the agent's finding.
type Result struct {
	ScanPage  *int   `json:"scan_page"`
	Reasoning string `json:"reasoning"`
}

// titleCase capitalizes the first letter of a string.
func titleCase(s string) string {
	if s == "" {
		return s
	}
	runes := []rune(s)
	runes[0] = unicode.ToUpper(runes[0])
	return string(runes)
}
