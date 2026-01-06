package extract_toc

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

// SystemPrompt returns the system prompt for ToC extraction.
func SystemPrompt() string {
	return systemPrompt
}

// Prompt keys
const (
	SystemPromptKey = "stages.extract_toc.system"
	UserPromptKey   = "stages.extract_toc.user"
)

// PromptKey is the hierarchical key for this prompt (alias for SystemPromptKey).
// Deprecated: Use SystemPromptKey instead.
const PromptKey = SystemPromptKey

// RegisterPrompts registers the extract_toc prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemPromptKey,
		Text:        systemPrompt,
		Description: "ToC extraction system prompt - extracts structured entries from ToC pages",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTmpl,
		Description: "ToC extraction user prompt template - provides ToC pages and structure for extraction",
	})
}

// UserPromptData contains the data needed to render the user prompt template.
type UserPromptData struct {
	TocPages         []ToCPage
	TotalPages       int
	StructureSummary *StructureSummary
}

// UserPrompt renders the user prompt template with the given data.
func UserPrompt(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userTemplate.Execute(&buf, data); err != nil {
		// Fallback to raw template on error
		return userPromptTmpl
	}
	return buf.String()
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
	return buf.String()
}

// ToCPage represents a single page of ToC content for extraction.
type ToCPage struct {
	PageNum int    `json:"page_num"`
	OCRText string `json:"ocr_text"`
}

// BuildUserPrompt builds the user prompt for ToC extraction.
// Deprecated: Use UserPrompt(UserPromptData) instead.
func BuildUserPrompt(tocPages []ToCPage, structureSummary *StructureSummary) string {
	return UserPrompt(UserPromptData{
		TocPages:         tocPages,
		TotalPages:       len(tocPages),
		StructureSummary: structureSummary,
	})
}
