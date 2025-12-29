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
								"description": "Exact text to find in Mistral output",
							},
							"replacement": map[string]any{
								"type":        "string",
								"description": "Corrected text",
							},
							"reason": map[string]any{
								"type":        "string",
								"description": "Brief explanation",
							},
						},
						"required":             []string{"original", "replacement", "reason"},
						"additionalProperties": false,
					},
					"description": "List of corrections to apply",
				},
				"confidence": map[string]any{
					"type":        "number",
					"description": "Overall confidence (0.0-1.0)",
				},
			},
			"required":             []string{"corrections", "confidence"},
			"additionalProperties": false,
		},
	},
}

// Correction represents a single OCR correction.
type Correction struct {
	Original    string `json:"original"`
	Replacement string `json:"replacement"`
	Reason      string `json:"reason"`
}

// Result represents the parsed result from blend LLM call.
type Result struct {
	Corrections []Correction `json:"corrections"`
	Confidence  float64      `json:"confidence"`
}
