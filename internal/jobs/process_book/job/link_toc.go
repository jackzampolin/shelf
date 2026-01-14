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
	// Get entries from BookState (loaded during LoadBook)
	if len(j.LinkTocEntries) == 0 {
		j.LinkTocEntries = j.Book.GetTocEntries()
	}

	// No entries to process
	if len(j.LinkTocEntries) == 0 {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("no ToC entries to link", "book_id", j.Book.BookID)
		}
		return nil
	}

	// Create work units for all entries
	var units []jobs.WorkUnit
	for _, entry := range j.LinkTocEntries {
		unit := j.CreateEntryFinderWorkUnit(ctx, entry)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units
}

// CreateEntryFinderWorkUnit creates an entry finder agent work unit.
func (j *Job) CreateEntryFinderWorkUnit(ctx context.Context, entry *toc_entry_finder.TocEntry) *jobs.WorkUnit {
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
			logger.Info("resuming ToC entry finder agent from saved state",
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

	// Store agent for later reference
	j.LinkTocEntryAgents[entry.DocID] = ag

	// Persist initial agent state (async, fire-and-forget)
	// This enables crash recovery to know this agent was started
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
	common.PersistAgentStateAsync(ctx, j.Book.BookID, initialState)
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
		if agentResult != nil && agentResult.Success {
			if entryResult, ok := agentResult.ToolResult.(*toc_entry_finder.Result); ok {
				// Update TocEntry with actual_page using common utility
				if err := common.SaveTocEntryResult(ctx, j.Book, info.EntryDocID, entryResult); err != nil {
					return nil, fmt.Errorf("failed to save entry result: %w", err)
				}
			}
		}

		j.LinkTocEntriesDone++
		delete(j.LinkTocEntryAgents, info.EntryDocID)
	}

	return nil, nil
}

// cleanupLinkTocAgentState removes link ToC entry agent state after completion.
func (j *Job) cleanupLinkTocAgentState(ctx context.Context, entryDocID string) {
	logger := svcctx.LoggerFrom(ctx)
	existing := j.Book.GetAgentState(common.AgentTypeTocEntryFinder, entryDocID)
	if existing != nil && existing.AgentID != "" {
		// Delete by agent_id since we don't have DocID from async create
		if err := common.DeleteAgentStateByAgentID(ctx, existing.AgentID); err != nil {
			if logger != nil {
				logger.Error("failed to delete agent state from DB, orphaned record remains",
					"agent_id", existing.AgentID,
					"agent_type", common.AgentTypeTocEntryFinder,
					"entry_doc_id", entryDocID,
					"book_id", j.Book.BookID,
					"error", err)
			}
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

// PersistTocLinkState persists ToC link state to DefraDB.
func (j *Job) PersistTocLinkState(ctx context.Context) error {
	tocLinkState := j.Book.GetTocLinkState()
	return common.PersistTocLinkState(ctx, j.TocDocID, &tocLinkState)
}

// StartFinalizeTocInline creates and starts the finalize phase inline.
// Returns work units to process. This is an alias to StartFinalizePhase for compatibility.
func (j *Job) StartFinalizeTocInline(ctx context.Context) []jobs.WorkUnit {
	return j.StartFinalizePhase(ctx)
}

// createLinkTocRetryUnit creates a retry work unit for a failed link_toc operation.
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

	// Remove old agent
	delete(j.LinkTocEntryAgents, info.EntryDocID)

	// Create new work unit
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
