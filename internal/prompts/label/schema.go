package label

// ExtractionSchema is the JSON schema for label extraction output.
var ExtractionSchema = map[string]any{
	"type": "json_schema",
	"json_schema": map[string]any{
		"name":   "unified_extraction",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"page_number": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Page number as printed (e.g., '34', 'xiv'), null if not found",
				},
				"running_header": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Running header text, null if not found",
				},
			},
			"required":             []string{"page_number", "running_header"},
			"additionalProperties": false,
		},
	},
}

// Result represents the parsed result from label extraction.
type Result struct {
	PageNumber    *string `json:"page_number"`
	RunningHeader *string `json:"running_header"`
}
