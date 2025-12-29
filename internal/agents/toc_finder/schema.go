package toc_finder

// Result represents the result from the ToC finder agent.
type Result struct {
	ToCFound           bool                   `json:"toc_found"`
	ToCPageRange       *PageRange             `json:"toc_page_range"`
	Confidence         float64                `json:"confidence"`
	SearchStrategyUsed string                 `json:"search_strategy_used"`
	Reasoning          string                 `json:"reasoning"`
	StructureSummary   *StructureSummary      `json:"structure_summary"`
	StructureNotes     map[int]string         `json:"structure_notes,omitempty"`
	PagesChecked       int                    `json:"pages_checked,omitempty"`
}

// PageRange represents the start and end pages of the ToC.
type PageRange struct {
	StartPage int `json:"start_page"`
	EndPage   int `json:"end_page"`
}

// StructureSummary describes the ToC hierarchy structure.
type StructureSummary struct {
	TotalLevels      int                      `json:"total_levels"`
	LevelPatterns    map[string]LevelPattern  `json:"level_patterns"`
	ConsistencyNotes []string                 `json:"consistency_notes,omitempty"`
}

// LevelPattern describes a single level in the ToC hierarchy.
type LevelPattern struct {
	Visual         string  `json:"visual"`
	Numbering      *string `json:"numbering"`
	HasPageNumbers bool    `json:"has_page_numbers"`
	SemanticType   *string `json:"semantic_type,omitempty"`
}
