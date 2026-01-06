package common

import (
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

	default:
		return ""
	}
}
