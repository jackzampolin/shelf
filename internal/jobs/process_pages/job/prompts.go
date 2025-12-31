package job

import (
	"context"

	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/prompts/blend"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/prompts/label"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// PromptKeys used by the process-pages job.
var promptKeys = []string{
	blend.PromptKey,
	label.SystemPromptKey,
	label.UserPromptKey,
	metadata.SystemPromptKey,
	metadata.UserPromptKey,
	extract_toc.PromptKey,
	toc_finder.PromptKey,
}

// ResolvePrompts resolves all prompts needed by this job.
// If a book-level override exists, it uses that; otherwise uses the embedded default.
// Results are cached in j.ResolvedPrompts for use throughout the job.
func (j *Job) ResolvePrompts(ctx context.Context) error {
	resolver := svcctx.PromptResolverFrom(ctx)
	logger := svcctx.LoggerFrom(ctx)

	for _, key := range promptKeys {
		var text string
		var cid string

		if resolver != nil {
			resolved, err := resolver.Resolve(ctx, key, j.BookID)
			if err != nil {
				if logger != nil {
					logger.Warn("failed to resolve prompt, using embedded default",
						"key", key, "book_id", j.BookID, "error", err)
				}
				// Fall through to use embedded default
			} else {
				text = resolved.Text
				cid = resolved.CID
				if resolved.IsOverride && logger != nil {
					logger.Info("using book-level prompt override",
						"key", key, "book_id", j.BookID)
				}
			}
		}

		// If we didn't get text from resolver, use embedded default
		if text == "" {
			text = getEmbeddedDefault(key)
		}

		j.ResolvedPrompts[key] = text
		j.ResolvedCIDs[key] = cid
	}

	if logger != nil {
		logger.Debug("resolved prompts for job", "book_id", j.BookID, "count", len(j.ResolvedPrompts))
	}

	return nil
}

// getEmbeddedDefault returns the embedded default for a prompt key.
func getEmbeddedDefault(key string) string {
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
	if text, ok := j.ResolvedPrompts[key]; ok && text != "" {
		return text
	}
	return getEmbeddedDefault(key)
}

// GetPromptCID returns the CID for a resolved prompt.
// Returns empty string if not available (e.g., when using embedded default without DB sync).
func (j *Job) GetPromptCID(key string) string {
	return j.ResolvedCIDs[key]
}
