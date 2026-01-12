package agents

import (
	"context"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs"
)

// ExecuteToolLoop runs tool calls synchronously until an LLM call or completion.
// Returns next work units (LLM type) or nil if agent is done.
//
// Tool calls are executed in-process since they're fast local operations (grep, file reads).
// Only LLM calls become work units dispatched to provider workers.
// After each tool batch, progress is persisted to show real-time agent status.
func ExecuteToolLoop(ctx context.Context, ag *agent.Agent) []agent.WorkUnit {
	for {
		units := ag.NextWorkUnits()
		if len(units) == 0 {
			return nil
		}

		// If these are tool calls, execute them synchronously
		if units[0].Type == agent.WorkUnitTypeTool {
			for _, unit := range units {
				if unit.ToolCall != nil {
					result, err := ag.ExecuteTool(ctx, *unit.ToolCall)
					ag.HandleToolResult(unit.ToolCall.ID, result, err)
				}
			}
			// Update progress after tool execution for real-time visibility
			ag.UpdateProgress(ctx)
			continue
		}

		// LLM call - update progress then return to caller for dispatch
		ag.UpdateProgress(ctx)
		return units
	}
}

// ConvertConfig provides context for work unit conversion.
type ConvertConfig struct {
	JobID     string // Job record ID for correlation
	Provider  string // LLM provider to use
	Stage     string // Pipeline stage (e.g., "process-book")
	ItemKey   string // Item identifier (e.g., "toc_finder")
	PromptKey string // Prompt key for tracing
	PromptCID string // Content-addressed prompt ID
	BookID    string // Book being processed
}

// ConvertToJobUnits converts agent work units to job work units.
// Only LLM work units are converted; tool work units should be executed synchronously.
// Priority is determined by the stage (book-level operations get PriorityHigh).
func ConvertToJobUnits(agentUnits []agent.WorkUnit, cfg ConvertConfig) []jobs.WorkUnit {
	var units []jobs.WorkUnit
	for _, au := range agentUnits {
		if au.Type != agent.WorkUnitTypeLLM || au.ChatRequest == nil {
			continue
		}
		units = append(units, jobs.WorkUnit{
			ID:          uuid.New().String(),
			Type:        jobs.WorkUnitTypeLLM,
			Provider:    cfg.Provider,
			JobID:       cfg.JobID,
			Priority:    jobs.PriorityForStage(cfg.ItemKey), // Use ItemKey for priority (e.g., "toc_finder")
			ChatRequest: au.ChatRequest,
			Tools:       au.Tools,
			Metrics: &jobs.WorkUnitMetrics{
				BookID:    cfg.BookID,
				Stage:     cfg.Stage,
				ItemKey:   cfg.ItemKey,
				PromptKey: cfg.PromptKey,
				PromptCID: cfg.PromptCID,
			},
		})
	}
	return units
}
