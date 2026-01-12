package blend

import (
	"encoding/json"
	"strings"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
)

// OCROutput represents the output from a single OCR provider.
type OCROutput struct {
	ProviderName string         // e.g., "mistral", "paddle"
	Text         string         // OCR markdown text
	Metadata     map[string]any // Optional provider-specific metadata
}

// Input contains the data needed for a blend work unit.
type Input struct {
	// OCROutputs from different providers. First provider is treated as PRIMARY.
	OCROutputs []OCROutput
	PageImage  []byte // Optional: page image for vision-based correction

	// SystemPromptOverride allows using a book-level system prompt override.
	// If empty, uses the embedded default.
	SystemPromptOverride string

	// UserPromptOverride allows using a book-level user prompt template override.
	// If empty, uses the embedded default template.
	UserPromptOverride string
}

// CreateWorkUnit creates a blend LLM work unit.
// The caller must set ID, JobID, and Provider on the returned unit.
func CreateWorkUnit(input Input) *jobs.WorkUnit {
	// Build user prompt data
	data := buildUserPromptData(input.OCROutputs)

	// Render user prompt with optional override
	userPrompt := UserPromptWithOverride(data, input.UserPromptOverride)

	systemPrompt := input.SystemPromptOverride
	if systemPrompt == "" {
		systemPrompt = SystemPrompt()
	}

	unit := &jobs.WorkUnit{
		Type: jobs.WorkUnitTypeLLM,
		ChatRequest: &providers.ChatRequest{
			Messages: []providers.Message{
				{Role: "system", Content: systemPrompt},
				{Role: "user", Content: userPrompt},
			},
			ResponseFormat: buildResponseFormat(),
			Temperature:    0.1,
			MaxTokens:      4096,
		},
	}

	// Add page image if provided (for vision-based correction)
	if len(input.PageImage) > 0 {
		unit.ChatRequest.Messages[1].Images = [][]byte{input.PageImage}
	}

	return unit
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

// ApplyCorrections applies corrections to the base text.
func ApplyCorrections(baseText string, corrections []Correction) string {
	result := baseText
	for _, c := range corrections {
		if c.Original != "" {
			result = replaceFirst(result, c.Original, c.Replacement)
		}
	}
	return result
}

func buildResponseFormat() *providers.ResponseFormat {
	jsonSchema, _ := json.Marshal(CorrectionsSchema["json_schema"])
	return &providers.ResponseFormat{
		Type:       "json_schema",
		JSONSchema: jsonSchema,
	}
}

func replaceFirst(s, old, new string) string {
	if old == "" {
		return s
	}
	for i := 0; i <= len(s)-len(old); i++ {
		if s[i:i+len(old)] == old {
			return s[:i] + new + s[i+len(old):]
		}
	}
	return s
}

// buildUserPromptData converts OCROutputs to UserPromptData for template rendering.
func buildUserPromptData(outputs []OCROutput) UserPromptData {
	data := UserPromptData{
		OCROutputs: make([]OCROutputData, 0, len(outputs)),
	}
	for _, out := range outputs {
		data.OCROutputs = append(data.OCROutputs, OCROutputData{
			TagName: strings.ToLower(out.ProviderName) + "_ocr",
			Text:    out.Text,
		})
	}
	return data
}

// PrimaryProviderName returns the name of the primary provider (first in list).
// Useful for applying corrections to the correct base text.
func PrimaryProviderName(outputs []OCROutput) string {
	if len(outputs) == 0 {
		return ""
	}
	return outputs[0].ProviderName
}

// GetOutputByProvider returns the OCR output for a specific provider.
func GetOutputByProvider(outputs []OCROutput, name string) (OCROutput, bool) {
	for _, out := range outputs {
		if strings.EqualFold(out.ProviderName, name) {
			return out, true
		}
	}
	return OCROutput{}, false
}
