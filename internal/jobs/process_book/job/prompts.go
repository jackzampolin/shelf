package job

import (
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// promptKeys used by the process-book job.
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

// GetPrompt returns the resolved prompt text for a key.
// Falls back to embedded default if not resolved.
func (j *Job) GetPrompt(key string) string {
	if text := j.Book.GetPrompt(key); text != "" {
		return text
	}
	return common.GetEmbeddedDefault(key)
}

// GetPromptCID returns the CID for a resolved prompt.
func (j *Job) GetPromptCID(key string) string {
	return j.Book.GetPromptCID(key)
}
