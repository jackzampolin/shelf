package common

import (
	"context"
	"fmt"
	"strings"
)

// --- Agent State Management ---

// AgentState tracks the state of an in-flight or completed agent for job resume.
// This allows agents to be restored from their conversation history after a crash.
type AgentState struct {
	// Identity
	AgentID   string // UUID for this agent instance
	AgentType string // "toc_finder", "toc_entry_finder", "chapter_finder", "gap_investigator"

	// Context - for multi-instance agents (like LinkToc entry agents)
	EntryDocID string // Which ToC entry this agent is for (if applicable)

	// Execution state
	Iteration int  // Current iteration number
	Complete  bool // Is agent done?

	// Conversation history (for resume) - JSON serialized
	MessagesJSON string // Serialized []providers.Message

	// In-flight tool call state (for resume mid-tool-execution) - JSON serialized
	PendingToolCalls string // Serialized []providers.ToolCall
	ToolResults      string // Serialized map[string]string (tool_call_id -> result)

	// Result (when complete) - JSON serialized
	ResultJSON string // Serialized agent.Result

	// Database identity
	DocID string // DefraDB document ID for this agent state
	CID   string // DefraDB commit CID for this agent state
}

// Valid agent types - used for validation
const (
	AgentTypeTocFinder       = "toc_finder"
	AgentTypeTocEntryFinder  = "toc_entry_finder"
	AgentTypeChapterFinder   = "chapter_finder"
	AgentTypeGapInvestigator = "gap_investigator"
)

// validAgentTypes is the set of valid agent type values.
var validAgentTypes = map[string]bool{
	AgentTypeTocFinder:       true,
	AgentTypeTocEntryFinder:  true,
	AgentTypeChapterFinder:   true,
	AgentTypeGapInvestigator: true,
}

// IsValidAgentType returns true if the agent type is valid.
func IsValidAgentType(agentType string) bool {
	return validAgentTypes[agentType]
}

// NewAgentState creates a new AgentState with validation.
// Returns an error if agentType is invalid or agentID is empty.
func NewAgentState(agentType, agentID string) (*AgentState, error) {
	if !IsValidAgentType(agentType) {
		return nil, fmt.Errorf("invalid agent type: %q (valid: %v)", agentType, []string{
			AgentTypeTocFinder, AgentTypeTocEntryFinder, AgentTypeChapterFinder, AgentTypeGapInvestigator,
		})
	}
	if agentID == "" {
		return nil, fmt.Errorf("agent_id is required")
	}
	return &AgentState{
		AgentType: agentType,
		AgentID:   agentID,
	}, nil
}

// AgentStateKey generates the map key for an agent state.
// Single agents use just their type, per-entry agents include entry doc ID.
func AgentStateKey(agentType string, entryDocID string) string {
	if entryDocID == "" {
		return agentType
	}
	return agentType + ":" + entryDocID
}

// GetAgentState returns the agent state for a given type and optional entry (thread-safe).
func (b *BookState) GetAgentState(agentType string, entryDocID string) *AgentState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	key := AgentStateKey(agentType, entryDocID)
	return b.agentStates[key]
}

// SetAgentState stores agent state (thread-safe).
func (b *BookState) SetAgentState(state *AgentState) {
	b.mu.Lock()
	defer b.mu.Unlock()
	key := AgentStateKey(state.AgentType, state.EntryDocID)
	b.agentStates[key] = state
	if state != nil {
		b.trackCIDLocked("AgentState", state.DocID, state.CID)
	}
}

// RemoveAgentState removes agent state (thread-safe).
func (b *BookState) RemoveAgentState(agentType string, entryDocID string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	key := AgentStateKey(agentType, entryDocID)
	delete(b.agentStates, key)
}

// GetAllAgentStates returns all agent states (thread-safe, returns a copy of keys).
func (b *BookState) GetAllAgentStates() []*AgentState {
	b.mu.RLock()
	defer b.mu.RUnlock()
	states := make([]*AgentState, 0, len(b.agentStates))
	for _, state := range b.agentStates {
		states = append(states, state)
	}
	return states
}

// ClearAgentStates removes all agent states for a given type (thread-safe).
// Use this when resetting an operation to clear associated agent state.
func (b *BookState) ClearAgentStates(agentType string) {
	b.mu.Lock()
	defer b.mu.Unlock()
	for key := range b.agentStates {
		// Match exact type or type:suffix for per-entry agents
		if key == agentType || strings.HasPrefix(key, agentType+":") {
			delete(b.agentStates, key)
		}
	}
}

// --- Agent Run Summary (for caching executed agent logs) ---

// AgentRunSummary is a lightweight summary of an agent execution.
// Used for caching agent run history on BookState.
type AgentRunSummary struct {
	DocID       string // DefraDB document ID
	AgentType   string // Agent type (toc_finder, chapter_finder, etc.)
	JobID       string // Job that spawned this agent
	StartedAt   string // ISO timestamp
	CompletedAt string // ISO timestamp (empty if still running)
	Iterations  int    // Number of agent iterations
	Success     bool   // Whether the agent succeeded
	Error       string // Error message if failed
}

// --- Agent Run Accessors ---
// Write-through cache: agent runs are added when agents complete.
// Lazy load: agent runs can be loaded from DB on first access if not already cached.

// AddAgentRun adds an agent run summary to the cache (thread-safe).
// Called when an agent completes execution.
func (b *BookState) AddAgentRun(run AgentRunSummary) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.agentRuns = append(b.agentRuns, run)
}

// GetAgentRuns returns cached agent run summaries (thread-safe).
// Returns a copy of the slice to prevent external modification.
func (b *BookState) GetAgentRuns() []AgentRunSummary {
	b.mu.RLock()
	defer b.mu.RUnlock()
	if b.agentRuns == nil {
		return nil
	}
	result := make([]AgentRunSummary, len(b.agentRuns))
	copy(result, b.agentRuns)
	return result
}

// GetAgentRunCount returns the number of cached agent runs (thread-safe).
func (b *BookState) GetAgentRunCount() int {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return len(b.agentRuns)
}

// AgentRunsLoaded returns true if agent runs have been loaded from DB (thread-safe).
func (b *BookState) AgentRunsLoaded() bool {
	b.mu.RLock()
	defer b.mu.RUnlock()
	return b.agentRunsLoaded
}

// SetAgentRuns sets agent runs from loaded data (thread-safe).
// Used when loading agent runs from DB.
func (b *BookState) SetAgentRuns(runs []AgentRunSummary) {
	b.mu.Lock()
	defer b.mu.Unlock()
	b.agentRuns = make([]AgentRunSummary, len(runs))
	copy(b.agentRuns, runs)
	b.agentRunsLoaded = true
}

// GetAgentRunsWithLazyLoad returns agent runs, loading from DB if needed (thread-safe).
// Requires context with DefraClient for DB queries.
func (b *BookState) GetAgentRunsWithLazyLoad(ctx context.Context) []AgentRunSummary {
	b.mu.RLock()
	if b.agentRunsLoaded {
		runs := make([]AgentRunSummary, len(b.agentRuns))
		copy(runs, b.agentRuns)
		b.mu.RUnlock()
		return runs
	}
	b.mu.RUnlock()

	// Need to load from DB - upgrade to write lock
	b.mu.Lock()
	defer b.mu.Unlock()

	// Double-check after acquiring write lock
	if b.agentRunsLoaded {
		result := make([]AgentRunSummary, len(b.agentRuns))
		copy(result, b.agentRuns)
		return result
	}

	// Load agent runs from DefraDB
	loadAgentRunsFromDB(ctx, b)
	result := make([]AgentRunSummary, len(b.agentRuns))
	copy(result, b.agentRuns)
	return result
}
