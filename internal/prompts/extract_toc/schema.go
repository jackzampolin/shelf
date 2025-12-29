package extract_toc

// ExtractionSchema is the JSON schema for ToC extraction output.
var ExtractionSchema = map[string]any{
	"type": "json_schema",
	"json_schema": map[string]any{
		"name":   "toc_extraction",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"entries": map[string]any{
					"type": "array",
					"items": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"entry_number": map[string]any{
								"type":        []string{"string", "null"},
								"description": "Entry numbering if present (e.g., '5', 'II', 'A', '1.1')",
							},
							"title": map[string]any{
								"type":        "string",
								"description": "Entry title as shown in ToC. Empty string '' for standalone markers like 'PART I'.",
							},
							"level": map[string]any{
								"type":        "integer",
								"minimum":     1,
								"maximum":     3,
								"description": "Visual hierarchy level (1=top-level, 2=nested, 3=deeply nested)",
							},
							"level_name": map[string]any{
								"type":        []string{"string", "null"},
								"description": "Semantic type: 'part', 'chapter', 'section', 'appendix', 'prologue', 'epilogue', 'introduction', 'notes', 'bibliography', 'index', etc.",
							},
							"printed_page_number": map[string]any{
								"type":        []string{"string", "null"},
								"description": "Page number exactly as printed (roman 'ix' or arabic '15')",
							},
						},
						"required":             []string{"title", "level"},
						"additionalProperties": false,
					},
					"description": "All ToC entries in top-to-bottom order",
				},
			},
			"required":             []string{"entries"},
			"additionalProperties": false,
		},
	},
}

// Entry represents a single extracted ToC entry.
type Entry struct {
	EntryNumber       *string `json:"entry_number"`
	Title             string  `json:"title"`
	Level             int     `json:"level"`
	LevelName         *string `json:"level_name"`
	PrintedPageNumber *string `json:"printed_page_number"`
}

// Result represents the parsed result from ToC extraction.
type Result struct {
	Entries []Entry `json:"entries"`
}

// StructureSummary describes the ToC hierarchy structure (from finder).
type StructureSummary struct {
	TotalLevels      int                       `json:"total_levels"`
	LevelPatterns    map[string]LevelPattern   `json:"level_patterns"`
	ConsistencyNotes []string                  `json:"consistency_notes,omitempty"`
}

// LevelPattern describes a single level in the ToC hierarchy.
type LevelPattern struct {
	Visual         string  `json:"visual"`
	Numbering      *string `json:"numbering"`
	HasPageNumbers bool    `json:"has_page_numbers"`
	SemanticType   *string `json:"semantic_type,omitempty"`
}
