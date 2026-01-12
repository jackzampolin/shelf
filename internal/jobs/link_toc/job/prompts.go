package job

import (
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// promptKeys are the prompts required for this job.
var promptKeys = []string{
	toc_entry_finder.PromptKey,
	toc_entry_finder.UserPromptKey,
}

// PromptKeys returns the prompt keys required for this job.
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
