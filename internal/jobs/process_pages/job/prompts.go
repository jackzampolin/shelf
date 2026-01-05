package job

import (
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
)

// promptKeys used by the process-pages job.
var promptKeys = []string{
	blend.PromptKey,
	label.SystemPromptKey,
	label.UserPromptKey,
	metadata.SystemPromptKey,
	metadata.UserPromptKey,
	extract_toc.PromptKey,
	toc_finder.PromptKey,
}

// PromptKeys returns the prompt keys needed by this job type.
// Used by common.LoadBook for prompt resolution.
func PromptKeys() []string {
	return promptKeys
}

// GetEmbeddedDefault returns the embedded default for a prompt key.
// Used by common.LoadBook as fallback when resolver doesn't have the prompt.
func GetEmbeddedDefault(key string) string {
	switch key {
	case blend.PromptKey:
		return blend.SystemPrompt()
	case label.SystemPromptKey:
		return label.SystemPrompt()
	case label.UserPromptKey:
		// User prompts are templates - return raw template
		return "" // Template handled separately
	case metadata.SystemPromptKey:
		return metadata.SystemPrompt()
	case metadata.UserPromptKey:
		// User prompts are templates - return raw template
		return "" // Template handled separately
	case extract_toc.PromptKey:
		return extract_toc.SystemPrompt()
	case toc_finder.PromptKey:
		return toc_finder.SystemPrompt()
	default:
		return ""
	}
}

// GetPrompt returns the resolved prompt text for a key.
// Falls back to embedded default if not resolved.
func (j *Job) GetPrompt(key string) string {
	if text, ok := j.Book.Prompts[key]; ok && text != "" {
		return text
	}
	return GetEmbeddedDefault(key)
}

// GetPromptCID returns the CID for a resolved prompt.
// Returns empty string if not available (e.g., when using embedded default without DB sync).
func (j *Job) GetPromptCID(key string) string {
	return j.Book.PromptCIDs[key]
}
