package metadata

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

// SystemPrompt returns the system prompt for metadata extraction.
func SystemPrompt() string {
	return systemPrompt
}

// UserPrompt builds the user prompt for metadata extraction.
func UserPrompt(bookText string) string {
	var buf bytes.Buffer
	data := struct{ BookText string }{BookText: bookText}
	if err := userTemplate.Execute(&buf, data); err != nil {
		return userPromptTmpl
	}
	return buf.String()
}

// Prompt keys
const (
	SystemPromptKey = "stages.metadata.system"
	UserPromptKey   = "stages.metadata.user"
)

// RegisterPrompts registers the metadata prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemPromptKey,
		Text:        systemPrompt,
		Description: "Metadata extraction system prompt - identifies book and extracts bibliographic data",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTmpl,
		Description: "Metadata extraction user prompt template",
	})
}
