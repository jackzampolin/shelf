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

// UserPromptData contains the data needed to render the user prompt template.
type UserPromptData struct {
	BookText string
}

// UserPrompt builds the user prompt for metadata extraction.
func UserPrompt(bookText string) string {
	return UserPromptFromData(UserPromptData{BookText: bookText})
}

// UserPromptFromData renders the user prompt template with the given data.
func UserPromptFromData(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userTemplate.Execute(&buf, data); err != nil {
		return userPromptTmpl
	}
	return buf.String()
}

// UserPromptWithOverride renders a user prompt, using an override template if provided.
func UserPromptWithOverride(data UserPromptData, override string) string {
	if override == "" {
		return UserPromptFromData(data)
	}
	// Parse and execute the override template
	tmpl, err := template.New("override").Parse(override)
	if err != nil {
		return UserPromptFromData(data) // Fallback to default on parse error
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return UserPromptFromData(data) // Fallback to default on execute error
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
