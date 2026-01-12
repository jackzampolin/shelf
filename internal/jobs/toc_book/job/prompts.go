package job

import (
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
)

// promptKeys used by the toc-book job.
var promptKeys = []string{
	// ToC finder agent
	toc_finder.SystemPromptKey,
	toc_finder.UserPromptKey,
	// ToC extraction stage
	extract_toc.SystemPromptKey,
	extract_toc.UserPromptKey,
}

// PromptKeys returns the prompt keys needed by this job type.
func PromptKeys() []string {
	return promptKeys
}

// GetPrompt returns the resolved prompt text for a key.
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
