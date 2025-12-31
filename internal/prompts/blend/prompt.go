package blend

import (
	_ "embed"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

// SystemPrompt returns the system prompt for OCR correction/blending.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for this prompt.
const PromptKey = "stages.blend.system"

// RegisterPrompts registers the blend prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "OCR correction/blending system prompt - compares image against multiple OCR outputs to identify errors",
	})
}
