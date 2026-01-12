package blend

// BlendSchema is the JSON schema for blend output.
var BlendSchema = map[string]any{
	"type": "json_schema",
	"json_schema": map[string]any{
		"name":   "ocr_blend",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"blended_text": map[string]any{
					"type":        "string",
					"description": "The final blended markdown text combining all OCR outputs",
				},
			},
			"required":             []string{"blended_text"},
			"additionalProperties": false,
		},
	},
}

// Result represents the parsed result from blend LLM call.
type Result struct {
	BlendedText string `json:"blended_text"`
}
