package schema

import (
	"embed"
	"fmt"
	"sort"
	"strings"
)

//go:embed schemas/*.graphql
var schemaFS embed.FS

// Schema represents a DefraDB collection schema.
type Schema struct {
	Name  string // Collection name (e.g., "Job")
	SDL   string // GraphQL SDL definition
	Order int    // Initialization order (lower = first)
}

// registry holds all schemas in dependency order.
// Order matters: parent collections must be created before children.
var registry = []Schema{
	{Name: "Config", Order: 0},              // standalone config settings, loaded first
	{Name: "Job", Order: 1},
	{Name: "Book", Order: 2},
	{Name: "Metric", Order: 3},              // standalone, no dependencies
	{Name: "Page", Order: 4},                // depends on Book
	{Name: "OcrResult", Order: 5},           // depends on Page
	{Name: "ToC", Order: 6},                 // depends on Book
	{Name: "TocEntry", Order: 7},            // depends on ToC, Page
	{Name: "Chapter", Order: 8},             // depends on Book, TocEntry
	{Name: "Paragraph", Order: 9},           // depends on Chapter
	{Name: "AgentRun", Order: 10},           // standalone, for debugging agent executions
	{Name: "AgentState", Order: 11},         // active agent state for resume, depends on Book
	{Name: "LLMCall", Order: 12},            // standalone, tracks all LLM API calls
	{Name: "Prompt", Order: 13},             // embedded prompt sync for UI/traceability
	{Name: "BookPromptOverride", Order: 14}, // per-book prompt customizations
	{Name: "Audio", Order: 15},              // TTS audiobook: AudioSegment, ChapterAudio, BookAudio
}

// All returns all schemas in dependency order.
// Schemas are loaded from embedded .graphql files.
func All() ([]Schema, error) {
	schemas := make([]Schema, len(registry))
	copy(schemas, registry)

	// Load SDL from embedded files
	for i := range schemas {
		filename := fmt.Sprintf("schemas/%s.graphql", lowercase(schemas[i].Name))
		content, err := schemaFS.ReadFile(filename)
		if err != nil {
			return nil, fmt.Errorf("failed to read schema %s: %w", schemas[i].Name, err)
		}
		schemas[i].SDL = string(content)
	}

	// Sort by order
	sort.Slice(schemas, func(i, j int) bool {
		return schemas[i].Order < schemas[j].Order
	})

	return schemas, nil
}

// Get returns a single schema by name.
func Get(name string) (*Schema, error) {
	for _, s := range registry {
		if s.Name == name {
			filename := fmt.Sprintf("schemas/%s.graphql", lowercase(s.Name))
			content, err := schemaFS.ReadFile(filename)
			if err != nil {
				return nil, fmt.Errorf("failed to read schema %s: %w", s.Name, err)
			}
			return &Schema{
				Name:  s.Name,
				SDL:   string(content),
				Order: s.Order,
			}, nil
		}
	}
	return nil, fmt.Errorf("schema not found: %s", name)
}

// lowercase converts a name to lowercase for filename lookup.
func lowercase(s string) string {
	return strings.ToLower(s)
}
