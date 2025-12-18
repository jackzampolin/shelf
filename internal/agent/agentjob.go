package agent

import (
	"context"
	"fmt"
	"sync"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/providers"
)

// AgentJob wraps an Agent to implement the jobs.Job interface.
// It converts agent WorkUnits to job WorkUnits and routes results back.
type AgentJob struct {
	mu sync.Mutex

	recordID string
	agent    *Agent

	// Track pending LLM work units
	pendingLLM map[string]bool // workUnitID -> true

	// Done tracking
	done bool
}

// NewAgentJob creates a job that runs an agent.
func NewAgentJob(agent *Agent) *AgentJob {
	return &AgentJob{
		agent:      agent,
		pendingLLM: make(map[string]bool),
	}
}

// ID returns the job's DefraDB record ID.
func (j *AgentJob) ID() string {
	return j.recordID
}

// SetRecordID sets the DefraDB record ID.
func (j *AgentJob) SetRecordID(id string) {
	j.recordID = id
}

// Type returns the job type.
func (j *AgentJob) Type() string {
	return "agent"
}

// Start initializes the job and returns initial work units.
func (j *AgentJob) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	return j.processAgentState(ctx)
}

// OnComplete handles a completed work unit.
func (j *AgentJob) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Remove from pending
	delete(j.pendingLLM, result.WorkUnitID)

	// Feed result to agent
	if result.ChatResult != nil {
		j.agent.HandleLLMResult(result.ChatResult)
	}

	// Process any tool calls and get next work units
	return j.processAgentStateLocked(ctx)
}

// Done returns true when the agent has completed.
func (j *AgentJob) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.done
}

// Status returns the current job status.
func (j *AgentJob) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	status := map[string]string{
		"agent_id":   j.agent.ID(),
		"iteration":  fmt.Sprintf("%d", j.agent.Iteration()),
		"done":       fmt.Sprintf("%t", j.agent.IsDone()),
		"pending_llm": fmt.Sprintf("%d", len(j.pendingLLM)),
	}

	if result := j.agent.Result(); result != nil {
		status["success"] = fmt.Sprintf("%t", result.Success)
		if result.Error != "" {
			status["error"] = result.Error
		}
	}

	return status, nil
}

// Progress returns provider progress.
func (j *AgentJob) Progress() map[string]jobs.ProviderProgress {
	return nil // Agent jobs don't have per-provider progress tracking
}

// MetricsFor returns nil for agent jobs (metrics not yet implemented).
func (j *AgentJob) MetricsFor() *jobs.WorkUnitMetrics {
	return nil
}

// Result returns the agent's result (only valid after Done() returns true).
func (j *AgentJob) Result() *Result {
	return j.agent.Result()
}

// processAgentState gets next work units and executes tools locally.
func (j *AgentJob) processAgentState(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.processAgentStateLocked(ctx)
}

// processAgentStateLocked must be called with j.mu held.
func (j *AgentJob) processAgentStateLocked(ctx context.Context) ([]jobs.WorkUnit, error) {
	for {
		// Check if agent is done
		if j.agent.IsDone() {
			j.done = true
			return nil, nil
		}

		// Get next work units from agent
		agentUnits := j.agent.NextWorkUnits()
		if len(agentUnits) == 0 {
			// Agent is done
			j.done = true
			return nil, nil
		}

		// Check what type of work units we have
		firstType := agentUnits[0].Type

		if firstType == WorkUnitTypeTool {
			// Execute tools locally
			for _, unit := range agentUnits {
				result, err := j.agent.ExecuteTool(ctx, *unit.ToolCall)
				j.agent.HandleToolResult(unit.ToolCall.ID, result, err)
			}
			// Loop to get next work units (could be more tools or LLM)
			continue
		}

		// LLM work units - convert to job work units
		var jobUnits []jobs.WorkUnit
		for _, unit := range agentUnits {
			workUnitID := uuid.New().String()
			j.pendingLLM[workUnitID] = true

			jobUnits = append(jobUnits, jobs.WorkUnit{
				ID:          workUnitID,
				Type:        jobs.WorkUnitTypeLLM,
				JobID:       j.recordID,
				ChatRequest: unit.ChatRequest,
				Tools:       unit.Tools, // Pass tools for ChatWithTools
			})
		}

		return jobUnits, nil
	}
}

// AgentJobConfig configures an agent job.
type AgentJobConfig struct {
	// Agent configuration
	ID              string
	Tools           Tools
	InitialMessages []providers.Message
	MaxIterations   int
}

// NewAgentJobFromConfig creates an agent job from configuration.
func NewAgentJobFromConfig(cfg AgentJobConfig) *AgentJob {
	agent := New(Config{
		ID:              cfg.ID,
		Tools:           cfg.Tools,
		InitialMessages: cfg.InitialMessages,
		MaxIterations:   cfg.MaxIterations,
	})
	return NewAgentJob(agent)
}
