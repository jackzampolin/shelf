package agent

import (
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

// Result holds the outcome of an agent run.
// Cost and token metrics are tracked separately by the metrics system.
type Result struct {
	Success bool   // Whether the agent completed successfully
	Error   string // Error message if failed

	// Iteration tracking
	Iterations    int // Number of LLM calls made
	MaxIterations int // Configured maximum

	// Timing
	ExecutionTime time.Duration

	// Conversation
	FinalMessages []providers.Message

	// Tool-specific result (from Tools.GetResult())
	ToolResult any
}
