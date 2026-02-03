package job

import (
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	pattern_analyzer "github.com/jackzampolin/shelf/internal/agents/pattern_analyzer"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// promptKeys used by the process-book job.
var promptKeys = []string{
	// Metadata stage
	metadata.SystemPromptKey,
	metadata.UserPromptKey,
	// ToC extraction stage
	extract_toc.SystemPromptKey,
	extract_toc.UserPromptKey,
	// ToC finder agent
	toc_finder.SystemPromptKey,
	toc_finder.UserPromptKey,
	// ToC entry finder agent (link_toc)
	toc_entry_finder.PromptKey,
	toc_entry_finder.UserPromptKey,
	// Finalize ToC agents (pattern analysis, chapter discovery, gap validation)
	pattern_analyzer.PromptKey,
	pattern_analyzer.UserPromptKey,
	chapter_finder.PromptKey,
	gap_investigator.PromptKey,
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
