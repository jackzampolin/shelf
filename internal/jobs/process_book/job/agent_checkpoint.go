package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// checkpointAgentState durably records a multi-turn agent immediately after an
// LLM response is incorporated. Persisting before the synchronous tool loop is
// intentional: on restart, pending tool calls can be replayed and the next LLM
// request keeps the correct iteration number instead of skipping a turn.
func (j *Job) checkpointAgentState(ctx context.Context, ag *agent.Agent, agentType, entryDocID string) error {
	if ag == nil {
		return fmt.Errorf("cannot checkpoint nil %s agent", agentType)
	}

	exported, err := ag.ExportState()
	if err != nil {
		return fmt.Errorf("export %s agent state: %w", agentType, err)
	}
	state := &common.AgentState{
		AgentID:          exported.AgentID,
		AgentType:        agentType,
		EntryDocID:       entryDocID,
		Iteration:        exported.Iteration,
		Complete:         exported.Complete,
		MessagesJSON:     exported.MessagesJSON,
		PendingToolCalls: exported.PendingToolCalls,
		ToolResults:      exported.ToolResults,
		ResultJSON:       exported.ResultJSON,
	}
	if err := common.PersistAgentState(ctx, j.Book, state); err != nil {
		return fmt.Errorf("persist %s agent checkpoint at iteration %d: %w", agentType, exported.Iteration, err)
	}
	return nil
}
