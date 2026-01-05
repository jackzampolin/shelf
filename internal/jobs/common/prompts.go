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
func GetEmbeddedDefault(key string) string {
	switch key {
	case blend.PromptKey:
		return blend.SystemPrompt()
	case label.SystemPromptKey:
		return label.SystemPrompt()
	case label.UserPromptKey:
		return "" // User prompts are templates
	case metadata.SystemPromptKey:
		return metadata.SystemPrompt()
	case metadata.UserPromptKey:
		return "" // User prompts are templates
	case extract_toc.PromptKey:
		return extract_toc.SystemPrompt()
	case toc_finder.PromptKey:
		return toc_finder.SystemPrompt()
	default:
		return ""
	}
}
