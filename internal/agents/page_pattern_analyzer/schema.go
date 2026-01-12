package page_pattern_analyzer

// Result aggregates the results from all pattern analysis calls.
type Result struct {
	PageNumberPattern *PageNumberPattern `json:"page_number_pattern"`
	BodyBoundaries    *BodyBoundaries    `json:"body_boundaries"`
	ChapterPatterns   []ChapterPattern   `json:"chapter_patterns"`
	Reasoning         string             `json:"reasoning"`
}

// PageNumberPattern describes the detected page numbering pattern.
type PageNumberPattern struct {
	Location      string `json:"location"`       // "top" or "bottom"
	Position      string `json:"position"`       // "left", "center", "right"
	Format        string `json:"format"`         // "numeric", "roman_lower", "roman_upper"
	StartPage     int    `json:"start_page"`     // First page with this pattern
	EndPage       *int   `json:"end_page"`       // Last page with this pattern (null if continues to end)
	StartValue    int    `json:"start_value"`    // First numeric value (e.g., 1)
	HasGaps       bool   `json:"has_gaps"`       // Whether sequence has gaps
	GapRanges     []Gap  `json:"gap_ranges"`     // Page ranges where numbering is missing
	Confidence    string `json:"confidence"`     // "high", "medium", "low"
	SamplePages   []int  `json:"sample_pages"`   // Pages that clearly show this pattern
	Reasoning     string `json:"reasoning"`      // Why this pattern was detected
}

// Gap represents a page range where page numbering is missing or irregular.
type Gap struct {
	StartPage int    `json:"start_page"`
	EndPage   int    `json:"end_page"`
	Reason    string `json:"reason"` // e.g., "front_matter", "toc", "missing"
}

// BodyBoundaries identifies where the main body text starts and ends.
type BodyBoundaries struct {
	BodyStartPage int    `json:"body_start_page"` // First page of body text
	BodyEndPage   *int   `json:"body_end_page"`   // Last page of body text (null if continues to end)
	Confidence    string `json:"confidence"`      // "high", "medium", "low"
	Reasoning     string `json:"reasoning"`       // Why these boundaries were detected
}

// ChapterPattern represents a detected chapter boundary pattern.
type ChapterPattern struct {
	ClusterID       string `json:"cluster_id"`       // Unique identifier for this cluster
	RunningHeader   string `json:"running_header"`   // The repeated text pattern
	StartPage       int    `json:"start_page"`       // First page with this pattern
	EndPage         int    `json:"end_page"`         // Last page with this pattern
	ChapterNumber   *int   `json:"chapter_number"`   // Detected chapter number (if numeric)
	ChapterTitle    string `json:"chapter_title"`    // Detected chapter title
	Confidence      string `json:"confidence"`       // "high", "medium", "low"
	Reasoning       string `json:"reasoning"`        // Why this is considered a chapter boundary
}

// PageLineData represents first/last lines from a single page.
type PageLineData struct {
	PageNum    int      `json:"page_num"`
	FirstLines []string `json:"first_lines"` // First 2 non-empty lines
	LastLines  []string `json:"last_lines"`  // Last 2 non-empty lines
}

// UserPromptData contains the data for rendering user prompts.
type UserPromptData struct {
	Pages      []PageLineData `json:"pages"`
	TotalPages int            `json:"total_pages"`
}

// PageNumberPatternSchema returns the JSON schema for page number pattern detection.
func PageNumberPatternSchema() map[string]any {
	return map[string]any{
		"type": "json_schema",
		"json_schema": map[string]any{
			"name":   "page_number_pattern",
			"strict": true,
			"schema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"page_number_pattern": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"location": map[string]any{
								"type": "string",
								"enum": []string{"top", "bottom"},
							},
							"position": map[string]any{
								"type": "string",
								"enum": []string{"left", "center", "right"},
							},
							"format": map[string]any{
								"type": "string",
								"enum": []string{"numeric", "roman_lower", "roman_upper"},
							},
							"start_page": map[string]any{
								"type": "integer",
							},
							"end_page": map[string]any{
								"type": []string{"integer", "null"},
							},
							"start_value": map[string]any{
								"type": "integer",
							},
							"has_gaps": map[string]any{
								"type": "boolean",
							},
							"gap_ranges": map[string]any{
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
							"confidence": map[string]any{
								"type": "string",
								"enum": []string{"high", "medium", "low"},
							},
							"sample_pages": map[string]any{
								"type": "array",
								"items": map[string]any{
									"type": "integer",
								},
							},
							"reasoning": map[string]any{
								"type": "string",
							},
						},
						"required": []string{
							"location", "position", "format", "start_page",
							"start_value", "has_gaps", "gap_ranges",
							"confidence", "sample_pages", "reasoning",
						},
						"additionalProperties": false,
					},
				},
				"required":             []string{"page_number_pattern"},
				"additionalProperties": false,
			},
		},
	}
}

// ChapterPatternsSchema returns the JSON schema for running header clustering.
func ChapterPatternsSchema() map[string]any {
	return map[string]any{
		"type": "json_schema",
		"json_schema": map[string]any{
			"name":   "chapter_patterns",
			"strict": true,
			"schema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"chapter_patterns": map[string]any{
						"type": "array",
						"items": map[string]any{
							"type": "object",
							"properties": map[string]any{
								"cluster_id": map[string]any{
									"type": "string",
								},
								"running_header": map[string]any{
									"type": "string",
								},
								"start_page": map[string]any{
									"type": "integer",
								},
								"end_page": map[string]any{
									"type": "integer",
								},
								"chapter_number": map[string]any{
									"type": []string{"integer", "null"},
								},
								"chapter_title": map[string]any{
									"type": "string",
								},
								"confidence": map[string]any{
									"type": "string",
									"enum": []string{"high", "medium", "low"},
								},
								"reasoning": map[string]any{
									"type": "string",
								},
							},
							"required": []string{
								"cluster_id", "running_header", "start_page",
								"end_page", "chapter_title", "confidence", "reasoning",
							},
							"additionalProperties": false,
						},
					},
					"reasoning": map[string]any{
						"type": "string",
					},
				},
				"required":             []string{"chapter_patterns", "reasoning"},
				"additionalProperties": false,
			},
		},
	}
}

// BodyBoundariesSchema returns the JSON schema for body boundary detection.
func BodyBoundariesSchema() map[string]any {
	return map[string]any{
		"type": "json_schema",
		"json_schema": map[string]any{
			"name":   "body_boundaries",
			"strict": true,
			"schema": map[string]any{
				"type": "object",
				"properties": map[string]any{
					"body_boundaries": map[string]any{
						"type": "object",
						"properties": map[string]any{
							"body_start_page": map[string]any{
								"type": "integer",
							},
							"body_end_page": map[string]any{
								"type": []string{"integer", "null"},
							},
							"confidence": map[string]any{
								"type": "string",
								"enum": []string{"high", "medium", "low"},
							},
							"reasoning": map[string]any{
								"type": "string",
							},
						},
						"required": []string{
							"body_start_page", "confidence", "reasoning",
						},
						"additionalProperties": false,
					},
				},
				"required":             []string{"body_boundaries"},
				"additionalProperties": false,
			},
		},
	}
}
