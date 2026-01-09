package common

import (
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/pattern_analyzer"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
)

// GetEmbeddedDefault returns the embedded default prompt for a key.
// This centralizes all prompt defaults so jobs don't duplicate this mapping.
// For user prompts (templates), returns empty string since they require template execution.
func GetEmbeddedDefault(key string) string {
	switch key {
	// Blend prompts
	case blend.SystemPromptKey:
		return blend.SystemPrompt()
	case blend.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// Label prompts
	case label.SystemPromptKey:
		return label.SystemPrompt()
	case label.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// Metadata prompts
	case metadata.SystemPromptKey:
		return metadata.SystemPrompt()
	case metadata.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// Extract ToC prompts
	case extract_toc.SystemPromptKey:
		return extract_toc.SystemPrompt()
	case extract_toc.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// ToC Finder prompts
	case toc_finder.SystemPromptKey:
		return toc_finder.SystemPrompt()
	case toc_finder.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// ToC Entry Finder prompts
	case toc_entry_finder.PromptKey:
		return toc_entry_finder.SystemPrompt()
	case toc_entry_finder.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// Pattern Analyzer prompts
	case pattern_analyzer.PromptKey:
		return pattern_analyzer.SystemPrompt()
	case pattern_analyzer.UserPromptKey:
		return "" // User prompts are templates, require data to render

	// Chapter Finder prompts
	case chapter_finder.PromptKey:
		return chapter_finder.SystemPrompt()

	// Gap Investigator prompts
	case gap_investigator.PromptKey:
		return gap_investigator.SystemPrompt()

	default:
		return ""
	}
}
