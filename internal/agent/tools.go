package agent

import (
	"context"

	"github.com/jackzampolin/shelf/internal/providers"
)

// Tools defines the interface that agent tool implementations must satisfy.
// Each stage creates its own Tools implementation with domain-specific tools.
//
// Example usage in a stage:
//
//	type TocFinderTools struct {
//	    storage   *BookStorage
//	    entry     *TocEntry
//	    result    *FinderResult  // Set by write_result tool
//	}
//
//	func (t *TocFinderTools) GetTools() []providers.Tool { ... }
//	func (t *TocFinderTools) ExecuteTool(ctx, name, args) (string, error) { ... }
//	func (t *TocFinderTools) IsComplete() bool { return t.result != nil }
//	func (t *TocFinderTools) GetResult() any { return t.result }
type Tools interface {
	// GetTools returns OpenAI-format tool definitions for the LLM.
	GetTools() []providers.Tool

	// ExecuteTool runs a tool and returns the result as a JSON string.
	// The agent loop calls this for each tool_call in the LLM response.
	ExecuteTool(ctx context.Context, name string, arguments map[string]any) (string, error)

	// IsComplete returns true when the agent has achieved its goal.
	// Typically set by a "write_result" or "submit_answer" tool.
	IsComplete() bool

	// GetImages returns images to include in the next LLM call (for vision models).
	// Returns nil if no images. Called before each LLM iteration.
	GetImages() [][]byte

	// GetResult returns the final result after IsComplete() returns true.
	// The type depends on the specific tools implementation.
	GetResult() any
}
