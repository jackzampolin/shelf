package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateLinkTocWorkUnits creates work units for all ToC entries.
// Must be called with j.Mu held.
func (j *Job) CreateLinkTocWorkUnits(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Get entries from BookState (loaded during LoadBook)
	if len(j.LinkTocEntries) == 0 {
		j.LinkTocEntries = j.Book.GetTocEntries()
	}

	// No entries to process
	if len(j.LinkTocEntries) == 0 {
		if logger != nil {
			logger.Debug("no ToC entries to link", "book_id", j.Book.BookID)
		}
		return nil
	}

	// Set total and check if already partially done (crash recovery)
	total, done := j.Book.GetTocLinkProgress()
	if total != len(j.LinkTocEntries) {
		// Initialize or update total - keep done count for crash recovery
		j.Book.SetTocLinkProgress(len(j.LinkTocEntries), done)
		// Persist progress (async - memory is authoritative during execution)
		common.PersistTocLinkProgressAsync(ctx, j.Book)
	}

	// Phase 1: Create all agents and collect initial states (without persisting individually)
	type agentWithState struct {
		entry        *toc_entry_finder.TocEntry
		agent        *agent.Agent
		initialState *common.AgentState
	}
	var agentsToCreate []agentWithState

	for _, entry := range j.LinkTocEntries {
		ag, state := j.createEntryFinderAgentWithState(ctx, entry)
		if ag != nil && state != nil {
			agentsToCreate = append(agentsToCreate, agentWithState{
				entry:        entry,
				agent:        ag,
				initialState: state,
			})
		}
	}

	if len(agentsToCreate) == 0 {
		return nil
	}

	// Phase 2: Batch persist all agent states
	states := make([]*common.AgentState, len(agentsToCreate))
	for i, aws := range agentsToCreate {
		states[i] = aws.initialState
	}
	if err := common.PersistAgentStates(ctx, j.Book, states); err != nil {
		if logger != nil {
			logger.Warn("failed to batch persist agent states", "error", err)
		}
	}

	// Phase 3: Store agents and states, then execute tool loops
	var units []jobs.WorkUnit
	for _, aws := range agentsToCreate {
		j.LinkTocEntryAgents[aws.entry.DocID] = aws.agent
		j.Book.SetAgentState(aws.initialState)

		// Execute tool loop to get first work unit
		agentUnits := agents.ExecuteToolLoop(ctx, aws.agent)
		if len(agentUnits) == 0 {
			if logger != nil {
				logger.Debug("agent produced no work units",
					"book_id", j.Book.BookID,
					"entry_doc_id", aws.entry.DocID)
			}
			continue
		}

		// Convert and collect work units
		jobUnits := j.convertLinkTocAgentUnits(agentUnits, aws.entry.DocID)
		if len(jobUnits) > 0 {
			units = append(units, jobUnits[0])
		}
	}

	return units
}

// createEntryFinderAgentWithState creates an entry finder agent and its initial state.
// Returns the agent and state without persisting - caller is responsible for batching persistence.
func (j *Job) createEntryFinderAgentWithState(ctx context.Context, entry *toc_entry_finder.TocEntry) (*agent.Agent, *common.AgentState) {
	logger := svcctx.LoggerFrom(ctx)

	// Estimate book structure for back matter detection
	bookStructure := &toc_entry_finder.BookStructure{
		TotalPages:      j.Book.TotalPages,
		BackMatterStart: int(float64(j.Book.TotalPages) * 0.8),
		BackMatterTypes: "footnotes, bibliography, index",
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
func (j *Job) CreateEntryFinderWorkUnit(ctx context.Context, entry *toc_entry_finder.TocEntry) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Create agent and initial state
	ag, initialState := j.createEntryFinderAgentWithState(ctx, entry)
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
	jobUnits := j.convertLinkTocAgentUnits(agentUnits, entry.DocID)
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

// HandleLinkTocComplete processes entry finder agent work unit completion.
// Must be called with j.Mu held.
func (j *Job) HandleLinkTocComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	ag, ok := j.LinkTocEntryAgents[info.EntryDocID]
	if !ok {
		return nil, fmt.Errorf("agent not found for entry %s", info.EntryDocID)
	}

	logger := svcctx.LoggerFrom(ctx)

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)

		// Note: No intermediate state persistence - crash recovery restarts from scratch
		// This eliminates the SendSync bottleneck that serialized agent execution

		// Execute tool loop
		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			// More work to do
			return j.convertLinkTocAgentUnits(agentUnits, info.EntryDocID), nil
		}
	}

	// Check if agent is done
	if ag.IsDone() {
		// Save agent log if debug enabled
		if err := ag.SaveLog(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		// Clean up agent state from BookState and DB
		j.cleanupLinkTocAgentState(ctx, info.EntryDocID)

		agentResult := ag.Result()

		// Check if agent was successful
		agentSuccess := false
		if agentResult != nil && agentResult.Success {
			if entryResult, ok := agentResult.ToolResult.(*toc_entry_finder.Result); ok {
				agentSuccess = true
				// Update TocEntry with actual_page using common utility
				cid, err := common.SaveTocEntryResult(ctx, j.Book, info.EntryDocID, entryResult)
				if err != nil {
					return nil, fmt.Errorf("failed to save entry result: %w", err)
				}
				if cid != "" {
					j.Book.SetTocCID(cid)
				}
				if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "TocEntry", info.EntryDocID, cid); err != nil {
					if logger != nil {
						logger.Warn("failed to update metric output ref", "error", err)
					}
				}
			}
		}

		// If agent failed, retry or mark as failed
		if !agentSuccess {
			// Check if we should retry
			if info.RetryCount < MaxBookOpRetries {
				if logger != nil {
					logger.Warn("ToC entry finder failed - retrying",
						"book_id", j.Book.BookID,
						"entry_doc_id", info.EntryDocID,
						"retry_count", info.RetryCount+1,
						"max_retries", MaxBookOpRetries)
				}
				// Remove old work unit from tracker before creating retry
				j.RemoveWorkUnit(result.WorkUnitID)
				// Create retry work unit (this creates a fresh agent)
				unit := j.createLinkTocRetryUnit(ctx, info)
				if unit != nil {
					return []jobs.WorkUnit{*unit}, nil
				}
				// If we can't create retry unit, fall through to mark as failed
			}

			// Max retries exceeded or retry creation failed - log and continue
			if logger != nil {
				logger.Error("ToC entry finder failed after max retries - skipping entry",
					"book_id", j.Book.BookID,
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"max_retries", MaxBookOpRetries)
			}
		}

		j.Book.IncrementTocLinkEntriesDone()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistTocLinkProgressAsync(ctx, j.Book)
		delete(j.LinkTocEntryAgents, info.EntryDocID)
	}

	return nil, nil
}

// cleanupLinkTocAgentState removes link ToC entry agent state after completion.
// Uses async delete to avoid blocking the critical path.
func (j *Job) cleanupLinkTocAgentState(ctx context.Context, entryDocID string) {
	j.cleanupLinkTocAgentStateWithMode(ctx, entryDocID, false)
}

// cleanupLinkTocAgentStateWithMode removes link ToC entry agent state with
// selectable delete behavior.
func (j *Job) cleanupLinkTocAgentStateWithMode(ctx context.Context, entryDocID string, syncDelete bool) {
	existing := j.Book.GetAgentState(common.AgentTypeTocEntryFinder, entryDocID)
	if existing != nil && existing.AgentID != "" {
		if syncDelete {
			// Retry paths must delete synchronously to avoid create collisions.
			if err := common.DeleteAgentStateByAgentID(ctx, existing.AgentID); err != nil {
				if logger := svcctx.LoggerFrom(ctx); logger != nil {
					logger.Warn("failed to delete toc entry finder agent state",
						"entry_doc_id", entryDocID,
						"agent_id", existing.AgentID,
						"error", err)
				}
			}
		} else {
			// Async delete - fire and forget to avoid blocking critical path.
			common.DeleteAgentStateByAgentIDAsync(ctx, existing.AgentID)
		}
	}
	j.Book.RemoveAgentState(common.AgentTypeTocEntryFinder, entryDocID)
}

// convertLinkTocAgentUnits converts agent work units to job work units.
func (j *Job) convertLinkTocAgentUnits(agentUnits []agent.WorkUnit, entryDocID string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     "toc-link",
		ItemKey:   fmt.Sprintf("link_entry_%s", entryDocID),
		PromptKey: toc_entry_finder.PromptKey,
		PromptCID: j.GetPromptCID(toc_entry_finder.PromptKey),
		BookID:    j.Book.BookID,
	})

	// Register work units
	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeLinkToc,
			EntryDocID: entryDocID,
		})
	}

	return jobUnits
}

// PersistTocLinkState persists ToC link state to DefraDB (async - memory is authoritative).
func (j *Job) PersistTocLinkState(ctx context.Context) {
	common.PersistOpStateAsync(ctx, j.Book, common.OpTocLink)
}

// StartFinalizeTocInline creates and starts the finalize phase inline.
// Returns work units to process. This is an alias to StartFinalizePhase for compatibility.
func (j *Job) StartFinalizeTocInline(ctx context.Context) []jobs.WorkUnit {
	return j.StartFinalizePhase(ctx)
}

// createLinkTocRetryUnit creates a retry work unit for a failed link_toc operation.
// Cleans up old agent state and creates a fresh agent (not resuming from failed state).
func (j *Job) createLinkTocRetryUnit(ctx context.Context, info WorkUnitInfo) *jobs.WorkUnit {
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
		return nil
	}

	// Remove old agent from map
	delete(j.LinkTocEntryAgents, info.EntryDocID)

	// Clean up old agent state from BookState and DB for fresh start.
	// Delete synchronously here to avoid create collisions on retry.
	j.cleanupLinkTocAgentStateWithMode(ctx, info.EntryDocID, true)

	// Create new work unit with fresh agent
	unit := j.CreateEntryFinderWorkUnit(ctx, entry)
	if unit != nil {
		// Update the registered info with incremented retry count
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeLinkToc,
			EntryDocID: info.EntryDocID,
			RetryCount: info.RetryCount + 1,
		})
	}

	return unit
}

// HandleFinalizeComplete routes finalize work unit completion to the appropriate handler.
func (j *Job) HandleFinalizeComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	switch info.UnitType {
	case WorkUnitTypeFinalizePattern:
		return j.HandleFinalizePatternComplete(ctx, result, info)
	case WorkUnitTypeFinalizeDiscover:
		return j.HandleFinalizeDiscoverComplete(ctx, result, info)
	case WorkUnitTypeFinalizeGap:
		return j.HandleFinalizeGapComplete(ctx, result, info)
	default:
		// Unknown finalize work unit type - log warning and remove
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("unknown finalize work unit type",
				"unit_type", info.UnitType,
				"work_unit_id", result.WorkUnitID,
				"book_id", j.Book.BookID)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, nil
	}
}

// MaybeStartStructureInline starts structure processing if finalize is complete.
// Returns work units to process.
func (j *Job) MaybeStartStructureInline(ctx context.Context) []jobs.WorkUnit {
	// Only start structure if finalize is complete and structure not yet started
	if !j.Book.TocFinalizeIsComplete() || !j.Book.StructureCanStart() {
		return nil
	}

	return j.StartStructurePhase(ctx)
}

// HandleStructureComplete routes structure work unit completion to the appropriate handler.
func (j *Job) HandleStructureComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	switch info.UnitType {
	case WorkUnitTypeStructureClassify:
		return j.HandleStructureClassifyComplete(ctx, result, info)
	case WorkUnitTypeStructurePolish:
		return j.HandleStructurePolishComplete(ctx, result, info)
	default:
		// Unknown structure work unit type - log warning and remove
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("unknown structure work unit type",
				"unit_type", info.UnitType,
				"work_unit_id", result.WorkUnitID,
				"book_id", j.Book.BookID)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, nil
	}
}
