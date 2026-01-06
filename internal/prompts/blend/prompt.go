package blend

import (
	"bytes"
	_ "embed"
	"strings"
	"text/template"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

//go:embed user.tmpl
var userPromptTmpl string

var userTemplate = template.Must(template.New("user").Parse(userPromptTmpl))

// SystemPrompt returns the system prompt for OCR correction/blending.
func SystemPrompt() string {
	return systemPrompt
}

// Prompt keys
const (
	SystemPromptKey = "stages.blend.system"
	UserPromptKey   = "stages.blend.user"
)

// PromptKey is the hierarchical key for this prompt (alias for SystemPromptKey).
// Deprecated: Use SystemPromptKey instead.
const PromptKey = SystemPromptKey

// RegisterPrompts registers the blend prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemPromptKey,
		Text:        systemPrompt,
		Description: "OCR correction/blending system prompt - compares image against multiple OCR outputs to identify errors",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTmpl,
		Description: "OCR correction/blending user prompt template - provides OCR outputs for comparison",
	})
}

// OCROutputData represents an OCR output formatted for the template.
type OCROutputData struct {
	TagName string // e.g., "mistral_ocr"
	Text    string
}

// UserPromptData contains the data needed to render the user prompt template.
type UserPromptData struct {
	OCROutputs []OCROutputData
}

// UserPrompt renders the user prompt template with the given data.
func UserPrompt(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userTemplate.Execute(&buf, data); err != nil {
		// Fallback to raw template on error
		return userPromptTmpl
	}
	return strings.TrimSpace(buf.String())
}

// UserPromptWithOverride renders a user prompt, using an override template if provided.
func UserPromptWithOverride(data UserPromptData, override string) string {
	if override == "" {
		return UserPrompt(data)
	}
	// Parse and execute the override template
	tmpl, err := template.New("override").Parse(override)
	if err != nil {
		return UserPrompt(data) // Fallback to default on parse error
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return UserPrompt(data) // Fallback to default on execute error
	}
	return strings.TrimSpace(buf.String())
}
