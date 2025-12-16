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

// registry holds all schemas in order.
var registry = []Schema{
	{Name: "Job", Order: 1},
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
