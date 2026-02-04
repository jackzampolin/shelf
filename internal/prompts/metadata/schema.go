package metadata

// ExtractionSchema is the JSON schema for metadata extraction output.
var ExtractionSchema = map[string]any{
	"type": "json_schema",
	"json_schema": map[string]any{
		"name":   "book_metadata",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"title": map[string]any{
					"type":        "string",
					"description": "Official book title (without subtitle)",
				},
				"subtitle": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Book subtitle if any",
				},
				"authors": map[string]any{
					"type":        "array",
					"items":       map[string]any{"type": "string"},
					"description": "Primary author names",
				},
				"isbn": map[string]any{
					"type":        []string{"string", "null"},
					"description": "ISBN-10 or ISBN-13 if found",
				},
				"lccn": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Library of Congress Control Number if found",
				},
				"publisher": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Publishing house name",
				},
				"publication_year": map[string]any{
					"type":        []string{"integer", "null"},
					"description": "Year of publication",
				},
				"language": map[string]any{
					"type":        "string",
					"description": "ISO 639-1 language code (e.g., 'en', 'es')",
				},
				"description": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Brief book summary (50-100 words, 2-3 sentences)",
				},
				"subjects": map[string]any{
					"type":        "array",
					"items":       map[string]any{"type": "string"},
					"description": "Subject keywords/topics",
				},
				"contributors": map[string]any{
					"type": "array",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"name": map[string]any{"type": "string"},
							"role": map[string]any{"type": "string"},
						},
						"required":             []string{"name", "role"},
						"additionalProperties": false,
					},
					"description": "Other contributors (editor, translator, illustrator)",
				},
				"confidence": map[string]any{
					"type":        "number",
					"description": "Confidence score 0.0-1.0",
				},
				"cover_page": map[string]any{
					"type":        []string{"integer", "null"},
					"description": "Scan page number (1-indexed) containing the book's front cover image",
				},
			},
			"required":             []string{"title", "authors", "language", "confidence"},
			"additionalProperties": false,
		},
	},
}

// Contributor represents a book contributor.
type Contributor struct {
	Name string `json:"name"`
	Role string `json:"role"`
}

// Result represents the parsed result from metadata extraction.
type Result struct {
	Title           string        `json:"title"`
	Subtitle        *string       `json:"subtitle"`
	Authors         []string      `json:"authors"`
	ISBN            *string       `json:"isbn"`
	LCCN            *string       `json:"lccn"`
	Publisher       *string       `json:"publisher"`
	PublicationYear *int          `json:"publication_year"`
	Language        string        `json:"language"`
	Description     *string       `json:"description"`
	Subjects        []string      `json:"subjects"`
	Contributors    []Contributor `json:"contributors"`
	Confidence      float64       `json:"confidence"`
	CoverPage       *int          `json:"cover_page"`
}
