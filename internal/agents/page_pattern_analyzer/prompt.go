package page_pattern_analyzer

import (
	"bytes"
	_ "embed"
	"text/template"

	"github.com/jackzampolin/shelf/internal/prompts"
)

// System prompts for each analysis type
//go:embed system_page_numbers.tmpl
var systemPageNumbersPrompt string

//go:embed system_chapters.tmpl
var systemChaptersPrompt string

//go:embed system_boundaries.tmpl
var systemBoundariesPrompt string

// User prompt templates
//go:embed user_page_numbers.tmpl
var userPageNumbersTmpl string

//go:embed user_chapters.tmpl
var userChaptersTmpl string

//go:embed user_boundaries.tmpl
var userBoundariesTmpl string

var (
	userPageNumbersTemplate = template.Must(template.New("page_numbers").Parse(userPageNumbersTmpl))
	userChaptersTemplate    = template.Must(template.New("chapters").Parse(userChaptersTmpl))
	userBoundariesTemplate  = template.Must(template.New("boundaries").Parse(userBoundariesTmpl))
)

// Prompt keys
const (
	SystemPageNumbersKey = "agents.page_pattern_analyzer.page_numbers.system"
	UserPageNumbersKey   = "agents.page_pattern_analyzer.page_numbers.user"

	SystemChaptersKey = "agents.page_pattern_analyzer.chapters.system"
	UserChaptersKey   = "agents.page_pattern_analyzer.chapters.user"

	SystemBoundariesKey = "agents.page_pattern_analyzer.boundaries.system"
	UserBoundariesKey   = "agents.page_pattern_analyzer.boundaries.user"
)

// RegisterPrompts registers all page_pattern_analyzer prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemPageNumbersKey,
		Text:        systemPageNumbersPrompt,
		Description: "Page pattern analyzer system prompt - detects page numbering patterns from last lines",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPageNumbersKey,
		Text:        userPageNumbersTmpl,
		Description: "Page pattern analyzer user prompt template - provides last lines from all pages",
	})

	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemChaptersKey,
		Text:        systemChaptersPrompt,
		Description: "Page pattern analyzer system prompt - detects chapter patterns from first lines",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserChaptersKey,
		Text:        userChaptersTmpl,
		Description: "Page pattern analyzer user prompt template - provides first lines from all pages",
	})

	r.Register(prompts.EmbeddedPrompt{
		Key:         SystemBoundariesKey,
		Text:        systemBoundariesPrompt,
		Description: "Page pattern analyzer system prompt - detects body boundaries using pattern results",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserBoundariesKey,
		Text:        userBoundariesTmpl,
		Description: "Page pattern analyzer user prompt template - provides pattern results for boundary detection",
	})
}

// SystemPageNumbersPrompt returns the system prompt for page number pattern detection.
func SystemPageNumbersPrompt() string {
	return systemPageNumbersPrompt
}

// SystemChaptersPrompt returns the system prompt for chapter pattern detection.
func SystemChaptersPrompt() string {
	return systemChaptersPrompt
}

// SystemBoundariesPrompt returns the system prompt for body boundary detection.
func SystemBoundariesPrompt() string {
	return systemBoundariesPrompt
}

// UserPageNumbersPrompt renders the user prompt for page number pattern detection.
func UserPageNumbersPrompt(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userPageNumbersTemplate.Execute(&buf, data); err != nil {
		return userPageNumbersTmpl
	}
	return buf.String()
}

// UserChaptersPrompt renders the user prompt for chapter pattern detection.
func UserChaptersPrompt(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userChaptersTemplate.Execute(&buf, data); err != nil {
		return userChaptersTmpl
	}
	return buf.String()
}

// BoundariesPromptData contains data for body boundary detection prompt.
type BoundariesPromptData struct {
	PageNumberPattern *PageNumberPattern `json:"page_number_pattern"`
	ChapterPatterns   []ChapterPattern   `json:"chapter_patterns"`
	TotalPages        int                `json:"total_pages"`
}

// UserBoundariesPrompt renders the user prompt for body boundary detection.
func UserBoundariesPrompt(data BoundariesPromptData) string {
	var buf bytes.Buffer
	if err := userBoundariesTemplate.Execute(&buf, data); err != nil {
		return userBoundariesTmpl
	}
	return buf.String()
}

// UserPageNumbersPromptWithOverride renders with an optional override template.
func UserPageNumbersPromptWithOverride(data UserPromptData, override string) string {
	if override == "" {
		return UserPageNumbersPrompt(data)
	}
	tmpl, err := template.New("override").Parse(override)
	if err != nil {
		return UserPageNumbersPrompt(data)
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return UserPageNumbersPrompt(data)
	}
	return buf.String()
}

// UserChaptersPromptWithOverride renders with an optional override template.
func UserChaptersPromptWithOverride(data UserPromptData, override string) string {
	if override == "" {
		return UserChaptersPrompt(data)
	}
	tmpl, err := template.New("override").Parse(override)
	if err != nil {
		return UserChaptersPrompt(data)
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return UserChaptersPrompt(data)
	}
	return buf.String()
}

// UserBoundariesPromptWithOverride renders with an optional override template.
func UserBoundariesPromptWithOverride(data BoundariesPromptData, override string) string {
	if override == "" {
		return UserBoundariesPrompt(data)
	}
	tmpl, err := template.New("override").Parse(override)
	if err != nil {
		return UserBoundariesPrompt(data)
	}
	var buf bytes.Buffer
	if err := tmpl.Execute(&buf, data); err != nil {
		return UserBoundariesPrompt(data)
	}
	return buf.String()
}
