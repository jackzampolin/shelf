package blend

// CorrectionsSchema is the JSON schema for blend corrections output.
var CorrectionsSchema = map[string]any{
	"type": "json_schema",
	"json_schema": map[string]any{
		"name":   "ocr_corrections",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"corrections": map[string]any{
					"type": "array",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"original": map[string]any{
								"type":        "string",
								"description": "Exact text to find in primary OCR output",
							},
							"replacement": map[string]any{
								"type":        "string",
								"description": "Corrected text",
							},
						},
						"required":             []string{"original", "replacement"},
						"additionalProperties": false,
					},
					"description": "List of corrections to apply. Empty array if no corrections needed.",
				},
			},
			"required":             []string{"corrections"},
			"additionalProperties": false,
		},
	},
}

// Correction represents a single OCR correction.
type Correction struct {
	Original    string `json:"original"`
	Replacement string `json:"replacement"`
}

// Result represents the parsed result from blend LLM call.
type Result struct {
	Corrections []Correction `json:"corrections"`
}
