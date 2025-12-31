package extract_toc

import (
	"encoding/json"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
)

// Input contains the data needed for a ToC extraction work unit.
type Input struct {
	ToCPages         []ToCPage
	StructureSummary *StructureSummary // Optional, from toc_finder

	// SystemPromptOverride allows using a book-level prompt override.
	// If empty, uses the embedded default.
	SystemPromptOverride string
}

// CreateWorkUnit creates a ToC extraction LLM work unit.
// The caller must set ID, JobID, and Provider on the returned unit.
func CreateWorkUnit(input Input) *jobs.WorkUnit {
	userPrompt := BuildUserPrompt(input.ToCPages, input.StructureSummary)

	systemPrompt := input.SystemPromptOverride
	if systemPrompt == "" {
		systemPrompt = SystemPrompt()
	}

	return &jobs.WorkUnit{
		Type: jobs.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{
			Messages: []providers.Message{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userPrompt},
			},
			ResponseFormat: buildResponseFormat(),
			Temperature:    0.1,
			MaxTokens:      8192, // ToC can be lengthy
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
