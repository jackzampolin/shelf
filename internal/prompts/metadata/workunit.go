package metadata

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Page represents a single page's OCR markdown text for metadata extraction.
type Page struct {
	PageNum     int
	OcrMarkdown string
}

// Input contains the data needed for a metadata work unit.
type Input struct {
	BookText string // OCR text from first ~20 pages

	// SystemPromptOverride allows using a book-level system prompt override.
	// If empty, uses the embedded default.
	SystemPromptOverride string

	// UserPromptOverride allows using a book-level user prompt template override.
	// If empty, uses the embedded default template.
	UserPromptOverride string
}

// PrepareBookText prepares book text from pages for metadata extraction.
// Takes the first maxPages pages and concatenates them with page separators.
func PrepareBookText(pages []Page, maxPages int) string {
	var parts []string
	for i, p := range pages {
		if i >= maxPages {
			break
		}
		if p.OcrMarkdown == "" {
			continue
		}
		parts = append(parts, fmt.Sprintf("--- Page %d ---\n%s", p.PageNum, p.OcrMarkdown))
	}
	return strings.Join(parts, "\n\n")
}

// CreateWorkUnit creates a metadata extraction LLM work unit.
// The caller must set ID, JobID, and Provider on the returned unit.
func CreateWorkUnit(input Input) *jobs.WorkUnit {
	systemPrompt := input.SystemPromptOverride
	if systemPrompt == "" {
		systemPrompt = SystemPrompt()
	}

	// Render user prompt with optional override
	data := UserPromptData{BookText: input.BookText}
	userPrompt := UserPromptWithOverride(data, input.UserPromptOverride)

	return &jobs.WorkUnit{
		Type: jobs.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{
			Messages: []providers.Message{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userPrompt},
			},
			ResponseFormat: buildResponseFormat(),
			Temperature:    0.1,
			MaxTokens:      2048,
		},
	}
}

// ParseResult parses the LLM response into a Result.
func ParseResult(parsedJSON any) (*Result, error) {
	jsonBytes, err := json.Marshal(parsedJSON)
	if err != nil {
		return nil, err
	}
	var result Result
	if err := json.Unmarshal(jsonBytes, &result); err != nil {
		return nil, err
	}
	return &result, nil
}

func buildResponseFormat() *providers.ResponseFormat {
	jsonSchema, _ := json.Marshal(ExtractionSchema["json_schema"])
	return &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: jsonSchema,
	}
}
