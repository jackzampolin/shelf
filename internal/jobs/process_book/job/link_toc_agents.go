package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

const maxLinkTocRetryHintBytes = 2000

// createEntryFinderAgentWithState creates an entry finder agent and its initial state.
// Returns the agent and state without persisting - caller is responsible for batching persistence.
func (j *Job) createEntryFinderAgentWithState(ctx context.Context, entry *toc_entry_finder.TocEntry, retryHint ...string) (*agent.Agent, *common.AgentState) {
	logger := svcctx.LoggerFrom(ctx)

	bookStructure := j.tocEntryBookStructure(ctx, entry)
	hint := strings.TrimSpace(firstString(retryHint))
	if hint != "" {
		if bookStructure == nil {
			bookStructure = &toc_entry_finder.BookStructure{}
		}
		bookStructure.RetryHint = hint
	}

	var ag *agent.Agent

	// Check for saved agent state (job resume case)
	savedState := j.Book.GetAgentState(common.AgentTypeTocEntryFinder, entry.DocID)
	if savedState != nil && !savedState.Complete {
		// Resume existing agent
		if logger != nil {
			logger.Debug("resuming ToC entry finder agent from saved state",
				"agent_id", savedState.AgentID,
				"entry_doc_id", entry.DocID,
				"iteration", savedState.Iteration)
		}

		// Create agent with fresh tools but restore conversation state
		ag = agents.NewTocEntryFinderAgent(ctx, agents.TocEntryFinderConfig{
			Book:          j.Book,
			SystemPrompt:  j.GetPrompt(toc_entry_finder.PromptKey),
			Entry:         entry,
			BookStructure: bookStructure,
			Debug:         j.Book.DebugAgents,
			JobID:         j.RecordID,
		})

		// Restore state from saved
		if err := ag.RestoreState(&agent.StateExport{
			AgentID:          savedState.AgentID,
			Iteration:        savedState.Iteration,
			Complete:         savedState.Complete,
			MessagesJSON:     savedState.MessagesJSON,
			PendingToolCalls: savedState.PendingToolCalls,
			ToolResults:      savedState.ToolResults,
			ResultJSON:       savedState.ResultJSON,
		}); err != nil {
			if logger != nil {
				logger.Warn("failed to restore ToC entry finder agent state, starting fresh",
					"entry_doc_id", entry.DocID,
					"error", err)
			}
			// Fall through to create fresh agent
			ag = nil
		}
	}

	// Create fresh agent if not restored
	if ag == nil {
		ag = agents.NewTocEntryFinderAgent(ctx, agents.TocEntryFinderConfig{
			Book:          j.Book,
			SystemPrompt:  j.GetPrompt(toc_entry_finder.PromptKey),
			Entry:         entry,
			BookStructure: bookStructure,
			Debug:         j.Book.DebugAgents,
			JobID:         j.RecordID,
		})
	}

	// Build initial state (don't persist yet)
	exported, _ := ag.ExportState()
	initialState := &common.AgentState{
		AgentID:          exported.AgentID,
		AgentType:        common.AgentTypeTocEntryFinder,
		EntryDocID:       entry.DocID,
		Iteration:        exported.Iteration,
		Complete:         false,
		MessagesJSON:     exported.MessagesJSON,
		PendingToolCalls: exported.PendingToolCalls,
		ToolResults:      exported.ToolResults,
		ResultJSON:       "",
	}

	return ag, initialState
}

// CreateEntryFinderWorkUnit creates an entry finder agent work unit.
// Used for single agent creation (e.g., retries). For batch creation, use CreateLinkTocWorkUnits.
func (j *Job) CreateEntryFinderWorkUnit(ctx context.Context, entry *toc_entry_finder.TocEntry, retryHint ...string) *jobs.WorkUnit {
	return j.createEntryFinderWorkUnit(ctx, entry, 0, firstString(retryHint))
}

func (j *Job) createEntryFinderWorkUnit(ctx context.Context, entry *toc_entry_finder.TocEntry, retryCount int, retryHint string) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Create agent and initial state
	ag, initialState := j.createEntryFinderAgentWithState(ctx, entry, retryHint)
	if ag == nil || initialState == nil {
		return nil
	}

	// Store agent for later reference
	j.LinkTocEntryAgents[entry.DocID] = ag

	// Persist single agent state (uses sync write)
	if err := common.PersistAgentState(ctx, j.Book, initialState); err != nil {
		if logger != nil {
			logger.Warn("failed to persist toc entry finder agent state",
				"entry_doc_id", entry.DocID,
				"error", err)
		}
	}
	j.Book.SetAgentState(initialState)

	// Get first work unit
	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		if logger != nil {
			logger.Debug("agent produced no work units",
				"book_id", j.Book.BookID,
				"entry_doc_id", entry.DocID)
		}
		return nil
	}

	// Convert and return first work unit
	jobUnits := j.convertLinkTocAgentUnits(agentUnits, entry.DocID, retryCount, retryHint)
	if len(jobUnits) == 0 {
		if logger != nil {
			logger.Debug("agent units converted to zero job units",
				"book_id", j.Book.BookID,
				"entry_doc_id", entry.DocID)
		}
		return nil
	}

	return &jobUnits[0]
}

// createLinkTocRetryUnit creates a retry work unit for a failed link_toc operation.
// Cleans up old agent state and creates a fresh agent with feedback from the rejection.
func (j *Job) createLinkTocRetryUnit(ctx context.Context, info WorkUnitInfo, retryReason error) (*jobs.WorkUnit, error) {
	// Find the entry for this doc ID
	var entry *toc_entry_finder.TocEntry
	for _, e := range j.LinkTocEntries {
		if e.DocID == info.EntryDocID {
			entry = e
			break
		}
	}
	if entry == nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("entry not found for retry",
				"book_id", j.Book.BookID,
				"entry_doc_id", info.EntryDocID)
		}
		return nil, fmt.Errorf("entry %s not found for retry", info.EntryDocID)
	}

	// Remove old agent from map
	delete(j.LinkTocEntryAgents, info.EntryDocID)

	// Clean up old agent state from BookState and DB for fresh start.
	// Delete synchronously here to avoid create collisions on retry.
	j.cleanupLinkTocAgentStateWithMode(ctx, info.EntryDocID, true)

	retryHint := appendLinkTocRetryHint(info.RetryHint, info.RetryCount, retryReason)
	newRetryCount := info.RetryCount + 1
	if err := common.PersistTocEntryLinkState(ctx, j.Book, info.EntryDocID, newRetryCount, false, retryHint); err != nil {
		return nil, fmt.Errorf("persist link retry for entry %s: %w", info.EntryDocID, err)
	}

	// Create new work unit with fresh agent and carry retry metadata through
	// every future LLM unit produced by this agent.
	unit := j.createEntryFinderWorkUnit(ctx, entry, newRetryCount, retryHint)
	if unit == nil {
		return nil, fmt.Errorf("create link retry for entry %s", info.EntryDocID)
	}
	return unit, nil
}

func linkTocWorkFailureReason(result jobs.WorkResult) error {
	if result.Error != nil && strings.TrimSpace(result.Error.Error()) != "" {
		msg := strings.TrimSpace(result.Error.Error())
		return fmt.Errorf("%s", msg)
	}
	return fmt.Errorf("link_toc work unit failed before the agent completed")
}

func appendLinkTocRetryHint(existing string, retryCount int, reason error) string {
	line := "Previous attempt was rejected."
	if reason != nil && strings.TrimSpace(reason.Error()) != "" {
		line = fmt.Sprintf("Attempt %d rejected: %s", retryCount+1, strings.TrimSpace(reason.Error()))
	}

	existing = strings.TrimSpace(existing)
	if existing != "" {
		line = existing + "\n" + line
	}
	if len(line) <= maxLinkTocRetryHintBytes {
		return line
	}
	return line[len(line)-maxLinkTocRetryHintBytes:]
}

func firstString(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[0]
}
