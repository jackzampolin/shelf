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

// PatternContext provides guidance from pattern analysis to help label extraction.
type PatternContext struct {
	// Page number expectations
	ExpectedPageNumber   *string // e.g., "45" or "xiv", null if in gap range
	PageNumberLocation   string  // "top" or "bottom"
	PageNumberPosition   string  // "left", "center", "right"
	PageNumberFormat     string  // "numeric", "roman_lower", "roman_upper"
	InPageNumberGap      bool    // True if this page is in a gap range (no page number expected)
	PageNumberGapReason  string  // e.g., "front_matter", "toc", "chapter_start"

	// Running header expectations
	ExpectedRunningHeader *string // Expected running header text from chapter patterns, null if none
	InRunningHeaderCluster bool   // True if this page is in a detected chapter cluster

	// Content classification hints
	ContentTypeHint   string // "body", "front_matter", "back_matter" from body boundaries
	IsInBodyRange     bool   // True if page is within detected body boundaries
	BodyStartPage     int    // First page of body (0 if not detected)
	BodyEndPage       int    // Last page of body (0 if not detected or continues to end)

	// Chapter detection hints
	NearChapterBoundary  bool    // True if within 2 pages of a detected chapter boundary
	ExpectedChapterNumber *string // Expected chapter number if detected, null otherwise
	ExpectedChapterTitle  *string // Expected chapter title if detected, null otherwise
}

// UserPromptData contains the data needed to render the user prompt template.
type UserPromptData struct {
	BlendedText    string
	PageNum        int
	PatternContext *PatternContext // Optional - provides guidance from pattern analysis
}

// UserPrompt builds the user prompt for label extraction.
func UserPrompt(blendedText string) string {
	return UserPromptFromData(UserPromptData{BlendedText: blendedText})
}

// UserPromptFromData renders the user prompt template with the given data.
func UserPromptFromData(data UserPromptData) string {
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
