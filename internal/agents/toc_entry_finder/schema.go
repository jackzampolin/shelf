package toc_entry_finder

// Result represents the result from the ToC entry finder agent.
type Result struct {
	ScanPage  *int   `json:"scan_page"`  // Actual page number where entry starts (nil if not found)
	Reasoning string `json:"reasoning"`  // How the agent found it or why not found
}

// TocEntry represents a ToC entry to find.
type TocEntry struct {
	DocID             string `json:"doc_id"`              // DefraDB document ID
	EntryNumber       string `json:"entry_number"`        // "5", "II", "A"
	Title             string `json:"title"`               // Chapter title
	Level             int    `json:"level"`               // Hierarchy level
	LevelName         string `json:"level_name"`          // "chapter", "part", "section"
	PrintedPageNumber string `json:"printed_page_number"` // From original ToC
	SortOrder         int    `json:"sort_order"`          // Position in ToC
}
