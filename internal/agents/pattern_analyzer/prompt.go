package pattern_analyzer

import (
	"bytes"
	_ "embed"
	"text/template"

	"github.com/jackzampolin/shelf/internal/prompts"
)

//go:embed system.tmpl
var systemPrompt string

//go:embed user.tmpl
var userPromptTemplate string

var userTmpl *template.Template

func init() {
	var err error
	userTmpl, err = template.New("user").Parse(userPromptTemplate)
	if err != nil {
		panic("failed to parse pattern_analyzer user template: " + err.Error())
	}
}

// SystemPrompt returns the system prompt for pattern analysis.
func SystemPrompt() string {
	return systemPrompt
}

// PromptKey is the hierarchical key for the system prompt.
const PromptKey = "agents.pattern_analyzer.system"

// UserPromptKey is the hierarchical key for the user prompt template.
const UserPromptKey = "agents.pattern_analyzer.user"

// RegisterPrompts registers the pattern_analyzer prompts with the resolver.
func RegisterPrompts(r *prompts.Resolver) {
	r.Register(prompts.EmbeddedPrompt{
		Key:         PromptKey,
		Text:        systemPrompt,
		Description: "Pattern analyzer system prompt - identifies chapter sequences missing from ToC",
	})
	r.Register(prompts.EmbeddedPrompt{
		Key:         UserPromptKey,
		Text:        userPromptTemplate,
		Description: "Pattern analyzer user prompt template - provides ToC entries and candidate headings",
	})
}

// LinkedEntry represents a ToC entry for the user prompt.
type LinkedEntry struct {
	Title       string
	EntryNumber string
	LevelName   string
	Level       int
	ActualPage  *int
}

// CandidateHeading represents a heading detected but not in ToC.
type CandidateHeading struct {
	PageNum int
	Text    string
	Level   int
}

// UserPromptData contains data for rendering the user prompt.
type UserPromptData struct {
	LinkedEntries       []LinkedEntry
	Candidates          []CandidateHeading
	CandidatesTruncated []CandidateHeading // Overflow candidates not shown
	BodyStart           int
	BodyEnd             int
	TotalPages          int
}

// BuildUserPrompt renders the user prompt with the given data.
func BuildUserPrompt(data UserPromptData) string {
	var buf bytes.Buffer
	if err := userTmpl.Execute(&buf, data); err != nil {
		// Fallback to raw template on error
		return userPromptTemplate
	}
	return buf.String()
}

// Result represents the parsed result from pattern analysis.
type Result struct {
	DiscoveredPatterns []DiscoveredPattern `json:"discovered_patterns"`
	ExcludedRanges     []ExcludedRange     `json:"excluded_page_ranges"`
	Reasoning          string              `json:"reasoning"`
}

// DiscoveredPattern represents a chapter sequence to discover.
type DiscoveredPattern struct {
	PatternType   string `json:"pattern_type"`
	LevelName     string `json:"level_name"`
	HeadingFormat string `json:"heading_format"`
	RangeStart    string `json:"range_start"`
	RangeEnd      string `json:"range_end"`
	Level         int    `json:"level"`
	Reasoning     string `json:"reasoning"`
}

// ExcludedRange represents a page range to skip.
type ExcludedRange struct {
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"`
}

// JSONSchema returns the JSON schema for structured output.
func JSONSchema() map[string]any {
	return map[string]any{
		"type": "json_schema",
		"json_schema": map[string]any{
			"name":   "pattern_analysis",
			"strict": true,
			"schema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"discovered_patterns": map[string]any{
						"type": "array",
						"items": map[string]any{
							"type": "object",
							"properties": map[string]any{
								"pattern_type":   map[string]any{"type": "string", "enum": []string{"sequential", "named"}},
								"level_name":     map[string]any{"type": []string{"string", "null"}},
								"range_start":    map[string]any{"type": []string{"string", "null"}},
								"range_end":      map[string]any{"type": []string{"string", "null"}},
								"level":          map[string]any{"type": []string{"integer", "null"}},
								"heading_format": map[string]any{"type": []string{"string", "null"}},
								"reasoning":      map[string]any{"type": "string"},
							},
							"required":             []string{"pattern_type", "reasoning"},
							"additionalProperties": false,
						},
					},
					"excluded_page_ranges": map[string]any{
						"type": "array",
						"items": map[string]any{
							"type": "object",
							"properties": map[string]any{
								"start_page": map[string]any{"type": "integer"},
								"end_page":   map[string]any{"type": "integer"},
								"reason":     map[string]any{"type": "string"},
							},
							"required":             []string{"start_page", "end_page", "reason"},
							"additionalProperties": false,
						},
					},
					"reasoning": map[string]any{"type": "string"},
				},
				"required":             []string{"discovered_patterns", "excluded_page_ranges", "reasoning"},
				"additionalProperties": false,
			},
		},
	}
}
