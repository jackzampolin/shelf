package label

import (
	"bytes"
	_ "embed"
	"text/template"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

//go:embed user.tmpl
var userPromptTmpl string

var userTemplate = template.Must(template.New("user").Parse(userPromptTmpl))

// SystemPrompt returns the system prompt for label structure extraction.
func SystemPrompt() string {
	return systemPrompt
}

// UserPrompt builds the user prompt for label extraction.
func UserPrompt(blendedText string) string {
	var buf bytes.Buffer
	data := struct{ BlendedText string }{BlendedText: blendedText}
	if err := userTemplate.Execute(&buf, data); err != nil {
		// Fallback to raw template on error
		return userPromptTmpl
	}
	return buf.String()
}

// Prompt keys
const (
	SystemPromptKey = "stages.label.system"
	UserPromptKey   = "stages.label.user"
)

// RegisterPrompts registers the label prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemPromptKey,
		Text:        systemPrompt,
		Description: "Label extraction system prompt - extracts page numbers and running headers",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTmpl,
		Description: "Label extraction user prompt template",
	})
}
