package job

import (
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
)

// promptKeys used by the ocr-book job.
var promptKeys = []string{
	blend.SystemPromptKey,
	blend.UserPromptKey,
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
