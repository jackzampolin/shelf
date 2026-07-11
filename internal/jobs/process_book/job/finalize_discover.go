package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// transitionToFinalizeDiscover moves to the discover phase.
func (j *Job) transitionToFinalizeDiscover(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Set phase and persist for crash recovery (async - memory is authoritative)
	j.Book.SetFinalizePhase(FinalizePhaseDiscover)
	common.PersistFinalizePhaseAsync(ctx, j.Book, FinalizePhaseDiscover)

	// Set entries total for progress tracking
	entriesToFindCount := j.Book.GetEntriesToFindCount()
	j.Book.SetFinalizeEntriesTotal(entriesToFindCount)

	if logger != nil {
		logger.Debug("transitioning to discover phase",
			"book_id", j.Book.BookID,
			"entries_to_find", entriesToFindCount)
	}

	// Persist progress with totals (async - memory is authoritative)
	common.PersistFinalizeProgressAsync(ctx, j.Book)

	if entriesToFindCount == 0 {
		return j.transitionToFinalizeValidate(ctx)
	}

	return j.createFinalizeDiscoverWorkUnits(ctx)
}

// createFinalizeDiscoverWorkUnits creates work units for all entries to discover.
func (j *Job) createFinalizeDiscoverWorkUnits(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)
	entries := j.Book.GetEntriesToFind()

	if len(entries) == 0 {
		return nil
	}

	// Phase 1: Create all agents and collect initial states
	type agentWithState struct {
		entry        *common.EntryToFind
		agent        *agent.Agent
		initialState *common.AgentState
	}
	var agentsToCreate []agentWithState

	for _, entry := range entries {
		ag, state := j.createChapterFinderAgentWithState(ctx, entry)
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
			logger.Warn("failed to batch persist chapter finder agent states", "error", err)
		}
	}

	// Phase 3: Store agents and states, then execute tool loops
	var units []jobs.WorkUnit
	for _, aws := range agentsToCreate {
		j.FinalizeDiscoverAgents[aws.entry.Key] = aws.agent
		j.Book.SetAgentState(aws.initialState)

		// Execute tool loop to get first work unit
		agentUnits := agents.ExecuteToolLoop(ctx, aws.agent)
		if len(agentUnits) == 0 {
			continue
		}

		// Convert and collect work units
		jobUnits := j.convertDiscoverAgentUnits(agentUnits, aws.entry.Key)
		if len(jobUnits) > 0 {
			units = append(units, jobUnits[0])
		}
	}

	return units
}

// createChapterFinderAgentWithState creates a chapter finder agent and its initial state.
// Returns the agent and state without persisting - caller is responsible for batching persistence.
func (j *Job) createChapterFinderAgentWithState(ctx context.Context, entry *common.EntryToFind) (*agent.Agent, *common.AgentState) {
	logger := svcctx.LoggerFrom(ctx)

	var excludedRanges []chapter_finder.ExcludedRange
	if j.Book.GetFinalizePatternResult() != nil {
		for _, ex := range j.Book.GetFinalizePatternResult().Excluded {
			excludedRanges = append(excludedRanges, chapter_finder.ExcludedRange{
				StartPage: ex.StartPage,
				EndPage:   ex.EndPage,
				Reason:    ex.Reason,
			})
		}
	}

	agentEntry := &chapter_finder.EntryToFind{
		LevelName:        entry.LevelName,
		Identifier:       entry.Identifier,
		HeadingFormat:    entry.HeadingFormat,
		ExpectedNearPage: entry.ExpectedNearPage,
		SearchRangeStart: entry.SearchRangeStart,
		SearchRangeEnd:   entry.SearchRangeEnd,
	}

	var ag *agent.Agent

	// Check for saved agent state (job resume case)
	savedState := j.Book.GetAgentState(common.AgentTypeChapterFinder, entry.Key)
	if savedState != nil && !savedState.Complete {
		// Resume existing agent
		if logger != nil {
			logger.Debug("resuming chapter finder agent from saved state",
				"agent_id", savedState.AgentID,
				"entry_key", entry.Key,
				"iteration", savedState.Iteration)
		}

		ag = agents.NewChapterFinderAgent(ctx, agents.ChapterFinderConfig{
			Book:           j.Book,
			SystemPrompt:   j.GetPrompt(chapter_finder.PromptKey),
			Entry:          agentEntry,
			ExcludedRanges: excludedRanges,
			Debug:          j.Book.DebugAgents,
			JobID:          j.RecordID,
		})

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
				logger.Warn("failed to restore chapter finder agent state, starting fresh",
					"entry_key", entry.Key,
					"error", err)
			}
			ag = nil
		}
	}

	// Create fresh agent if not restored
	if ag == nil {
		ag = agents.NewChapterFinderAgent(ctx, agents.ChapterFinderConfig{
			Book:           j.Book,
			SystemPrompt:   j.GetPrompt(chapter_finder.PromptKey),
			Entry:          agentEntry,
			ExcludedRanges: excludedRanges,
			Debug:          j.Book.DebugAgents,
			JobID:          j.RecordID,
		})
	}

	// Build initial state (don't persist yet)
	exported, _ := ag.ExportState()
	initialState := &common.AgentState{
		AgentID:          exported.AgentID,
		AgentType:        common.AgentTypeChapterFinder,
		EntryDocID:       entry.Key,
		Iteration:        exported.Iteration,
		Complete:         false,
		MessagesJSON:     exported.MessagesJSON,
		PendingToolCalls: exported.PendingToolCalls,
		ToolResults:      exported.ToolResults,
		ResultJSON:       "",
	}

	return ag, initialState
}

// createChapterFinderWorkUnit creates a chapter finder agent work unit.
// Used for single agent creation (e.g., retries). For batch creation, use createFinalizeDiscoverWorkUnits.
func (j *Job) createChapterFinderWorkUnit(ctx context.Context, entry *common.EntryToFind) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Create agent and initial state
	ag, initialState := j.createChapterFinderAgentWithState(ctx, entry)
	if ag == nil || initialState == nil {
		return nil
	}

	j.FinalizeDiscoverAgents[entry.Key] = ag

	// Persist single agent state (uses sync write)
	if err := common.PersistAgentState(ctx, j.Book, initialState); err != nil {
		if logger != nil {
			logger.Warn("failed to persist chapter finder agent state",
				"entry_key", entry.Key,
				"error", err)
		}
	}
	j.Book.SetAgentState(initialState)

	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		return nil
	}

	jobUnits := j.convertDiscoverAgentUnits(agentUnits, entry.Key)
	if len(jobUnits) == 0 {
		return nil
	}

	return &jobUnits[0]
}

// HandleFinalizeDiscoverComplete processes chapter finder completion.
func (j *Job) HandleFinalizeDiscoverComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)

	ag, ok := j.FinalizeDiscoverAgents[info.FinalizeKey]
	if !ok {
		j.RemoveWorkUnit(result.WorkUnitID)
		j.Book.IncrementFinalizeEntriesComplete()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistFinalizeProgressAsync(ctx, j.Book)
		return j.checkFinalizeDiscoverCompletion(ctx), nil
	}

	if !result.Success {
		if info.RetryCount < MaxFinalizeRetries {
			if logger != nil {
				logger.Warn("chapter finder failed, retrying",
					"entry_key", info.FinalizeKey,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryFinalizeDiscoverUnit(ctx, info)
		}
		j.Book.IncrementFinalizeEntriesComplete()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistFinalizeProgressAsync(ctx, j.Book)
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("chapter finder permanently failed",
				"entry_key", info.FinalizeKey,
				"error", result.Error)
		}
		return j.checkFinalizeDiscoverCompletion(ctx), nil
	}

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)
		if err := j.checkpointAgentState(ctx, ag, common.AgentTypeChapterFinder, info.FinalizeKey); err != nil {
			return nil, err
		}

		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			return j.convertDiscoverAgentUnits(agentUnits, info.FinalizeKey), nil
		}
	}

	// Check if agent is done
	if ag.IsDone() {
		if err := ag.SaveLog(ctx); err != nil {
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		// Clean up agent state
		j.cleanupFinalizeDiscoverAgentState(ctx, info.FinalizeKey)

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if finderResult, ok := agentResult.ToolResult.(*chapter_finder.Result); ok {
				writeResult, err := j.saveDiscoveredEntry(ctx, info.FinalizeKey, finderResult)
				if err != nil {
					if logger != nil {
						logger.Warn("failed to save discovered entry", "error", err)
					}
				} else if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "TocEntry", writeResult.DocID, writeResult.CID); err != nil {
					if logger != nil {
						logger.Warn("failed to update metric output ref", "error", err)
					}
				}
				if finderResult.ScanPage != nil && *finderResult.ScanPage > 0 {
					j.Book.IncrementFinalizeEntriesFound()
				}
			}
		}

		j.Book.IncrementFinalizeEntriesComplete()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistFinalizeProgressAsync(ctx, j.Book)
		delete(j.FinalizeDiscoverAgents, info.FinalizeKey)
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkFinalizeDiscoverCompletion(ctx), nil
}

// checkFinalizeDiscoverCompletion checks if discover phase is complete.
func (j *Job) checkFinalizeDiscoverCompletion(ctx context.Context) []jobs.WorkUnit {
	entriesComplete, _, _, _ := j.Book.GetFinalizeProgress()
	if entriesComplete >= j.Book.GetEntriesToFindCount() {
		return j.transitionToFinalizeValidate(ctx)
	}
	return nil
}

func (j *Job) saveDiscoveredEntry(ctx context.Context, entryKey string, result *chapter_finder.Result) (defra.WriteResult, error) {
	if result.ScanPage == nil || *result.ScanPage == 0 {
		return defra.WriteResult{}, nil
	}

	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return defra.WriteResult{}, fmt.Errorf("defra client not in context")
	}

	var entry *common.EntryToFind
	for _, e := range j.Book.GetEntriesToFind() {
		if e.Key == entryKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return defra.WriteResult{}, fmt.Errorf("entry not found: %s", entryKey)
	}
	if discoveredEntryAlreadyLinked(j.Book.GetLinkedEntries(), entry, *result.ScanPage) {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Info("skipping duplicate discovered ToC entry",
				"book_id", j.Book.BookID,
				"entry_key", entryKey,
				"identifier", entry.Identifier,
				"scan_page", *result.ScanPage)
		}
		return defra.WriteResult{}, nil
	}

	pageDocID := j.getPageDocID(*result.ScanPage)
	sortOrder := *result.ScanPage * 1000
	title := fmt.Sprintf("%s %s", titleCase(entry.LevelName), entry.Identifier)
	uniqueKey := fmt.Sprintf("%s:discovered:%s", j.TocDocID, entryKey)

	entryData := map[string]any{
		"_tocID":       j.TocDocID,
		"unique_key":   uniqueKey,
		"entry_number": entry.Identifier,
		"title":        title,
		"level":        entry.Level,
		"level_name":   entry.LevelName,
		"sort_order":   sortOrder,
		"source":       "discovered",
	}

	if pageDocID != "" {
		entryData["_actual_pageID"] = pageDocID
	}

	filter := map[string]any{
		"unique_key": map[string]any{"_eq": uniqueKey},
	}

	writeResult, err := defraClient.UpsertWithVersion(ctx, "TocEntry", filter, entryData, entryData)
	if err != nil {
		return defra.WriteResult{}, fmt.Errorf("failed to upsert discovered entry: %w", err)
	}
	j.Book.TrackWrite("TocEntry", writeResult.DocID, writeResult.CID)

	return writeResult, nil
}
