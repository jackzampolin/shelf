package label

// ExtractionSchema is the JSON schema for label extraction output.
var ExtractionSchema = map[string]any{
	"type": "json_schema",
	"json_schema": map[string]any{
		"name":   "page_label_extraction",
		"strict": true,
		"schema": map[string]any{
			"type": "object",
			"properties": map[string]any{
				"page_number": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Page number as printed (e.g., '34', 'xiv'), null if not found or in gap range",
				},
				"running_header": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Running header text, null if not found",
				},
				"content_type": map[string]any{
					"type": "string",
					"enum": []string{
						"body",
						"front_matter",
						"back_matter",
						"toc",
						"blank",
						"title_page",
						"copyright",
						"other",
					},
					"description": "Classification of page content type",
				},
				"is_chapter_start": map[string]any{
					"type":        "boolean",
					"description": "True if this page starts a new chapter",
				},
				"chapter_number": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Chapter number if detected (e.g., '5', 'XII'), null otherwise",
				},
				"chapter_title": map[string]any{
					"type":        []string{"string", "null"},
					"description": "Chapter title if this is a chapter start, null otherwise",
				},
				"is_blank_page": map[string]any{
					"type":        "boolean",
					"description": "True if page is mostly empty/whitespace",
				},
				"has_footnotes": map[string]any{
					"type":        "boolean",
					"description": "True if page contains footnote markers/text",
				},
			},
			"required": []string{
				"page_number",
				"running_header",
				"content_type",
				"is_chapter_start",
				"is_blank_page",
				"has_footnotes",
			},
			"additionalProperties": false,
		},
	},
}

// Result represents the parsed result from label extraction.
type Result struct {
	PageNumber     *string `json:"page_number"`
	RunningHeader  *string `json:"running_header"`
	ContentType    string  `json:"content_type"`
	IsChapterStart bool    `json:"is_chapter_start"`
	ChapterNumber  *string `json:"chapter_number"`
	ChapterTitle   *string `json:"chapter_title"`
	IsBlankPage    bool    `json:"is_blank_page"`
	HasFootnotes   bool    `json:"has_footnotes"`
}
