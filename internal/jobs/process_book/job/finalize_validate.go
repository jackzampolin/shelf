package job

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// findFinalizeGaps identifies gaps in page coverage.
func (j *Job) findFinalizeGaps(ctx context.Context) error {
	// Refresh linked entries to include discoveries
	entries, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		return err
	}

	// Sort entries by actual page
	sortedEntries := make([]*common.LinkedTocEntry, 0, len(entries))
	for _, e := range entries {
		if e.ActualPage != nil {
			sortedEntries = append(sortedEntries, e)
		}
	}
	sort.Slice(sortedEntries, func(i, k int) bool {
		return *sortedEntries[i].ActualPage < *sortedEntries[k].ActualPage
	})

	// Clear previous gaps
	j.Book.SetFinalizeGaps(nil)

	// Check gap from body start to first entry
	if len(sortedEntries) > 0 {
		first := sortedEntries[0]
		if *first.ActualPage-j.Book.GetBodyStart() > MinGapSize {
			j.Book.AppendFinalizeGap(&common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", j.Book.GetBodyStart(), *first.ActualPage-1),
				StartPage:      j.Book.GetBodyStart(),
				EndPage:        *first.ActualPage - 1,
				Size:           *first.ActualPage - j.Book.GetBodyStart(),
				NextEntryTitle: first.Title,
				NextEntryPage:  *first.ActualPage,
			})
		}
	}

	// Check gaps between consecutive entries
	for i := 0; i < len(sortedEntries)-1; i++ {
		curr := sortedEntries[i]
		next := sortedEntries[i+1]

		gapSize := *next.ActualPage - *curr.ActualPage
		if gapSize > MinGapSize {
			if j.isPageExcluded(*curr.ActualPage + 1) {
				continue
			}

			j.Book.AppendFinalizeGap(&common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", *curr.ActualPage+1, *next.ActualPage-1),
				StartPage:      *curr.ActualPage + 1,
				EndPage:        *next.ActualPage - 1,
				Size:           gapSize - 1,
				PrevEntryTitle: curr.Title,
				PrevEntryPage:  *curr.ActualPage,
				NextEntryTitle: next.Title,
				NextEntryPage:  *next.ActualPage,
			})
		}
	}

	// Check gap from last entry to body end
	if len(sortedEntries) > 0 {
		last := sortedEntries[len(sortedEntries)-1]
		if j.Book.GetBodyEnd()-*last.ActualPage > MinGapSize && !j.isPageExcluded(*last.ActualPage+1) {
			j.Book.AppendFinalizeGap(&common.FinalizeGap{
				Key:            fmt.Sprintf("gap_%d_%d", *last.ActualPage+1, j.Book.GetBodyEnd()),
				StartPage:      *last.ActualPage + 1,
				EndPage:        j.Book.GetBodyEnd(),
				Size:           j.Book.GetBodyEnd() - *last.ActualPage,
				PrevEntryTitle: last.Title,
				PrevEntryPage:  *last.ActualPage,
			})
		}
	}

	return nil
}

// isPageExcluded checks if a page is in an excluded range.
func (j *Job) isPageExcluded(page int) bool {
	if j.Book.GetFinalizePatternResult() == nil {
		return false
	}
	for _, ex := range j.Book.GetFinalizePatternResult().Excluded {
		if page >= ex.StartPage && page <= ex.EndPage {
			return true
		}
	}
	return false
}

// createFinalizeGapWorkUnits creates work units for gap investigation.
func (j *Job) createFinalizeGapWorkUnits(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)
	gaps := j.Book.GetFinalizeGaps()

	if len(gaps) == 0 {
		return nil
	}

	// Phase 1: Create all agents and collect initial states
	type agentWithState struct {
		gap          *common.FinalizeGap
		agent        *agent.Agent
		initialState *common.AgentState
	}
	var agentsToCreate []agentWithState

	for _, gap := range gaps {
		ag, state := j.createGapInvestigatorAgentWithState(ctx, gap)
		if ag != nil && state != nil {
			agentsToCreate = append(agentsToCreate, agentWithState{
				gap:          gap,
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
			logger.Warn("failed to batch persist gap investigator agent states", "error", err)
		}
	}

	// Phase 3: Store agents and states, then execute tool loops
	var units []jobs.WorkUnit
	for _, aws := range agentsToCreate {
		j.FinalizeGapAgents[aws.gap.Key] = aws.agent
		j.Book.SetAgentState(aws.initialState)

		// Execute tool loop to get first work unit
		agentUnits := agents.ExecuteToolLoop(ctx, aws.agent)
		if len(agentUnits) == 0 {
			continue
		}

		// Convert and collect work units
		jobUnits := j.convertGapAgentUnits(agentUnits, aws.gap.Key)
		if len(jobUnits) > 0 {
			units = append(units, jobUnits[0])
		}
	}

	return units
}

// createGapInvestigatorAgentWithState creates a gap investigator agent and its initial state.
// Returns the agent and state without persisting - caller is responsible for batching persistence.
func (j *Job) createGapInvestigatorAgentWithState(ctx context.Context, gap *common.FinalizeGap) (*agent.Agent, *common.AgentState) {
	logger := svcctx.LoggerFrom(ctx)

	agentGap := &gap_investigator.GapInfo{
		StartPage:      gap.StartPage,
		EndPage:        gap.EndPage,
		Size:           gap.Size,
		PrevEntryTitle: gap.PrevEntryTitle,
		PrevEntryPage:  gap.PrevEntryPage,
		NextEntryTitle: gap.NextEntryTitle,
		NextEntryPage:  gap.NextEntryPage,
	}

	// Get linked entries
	entries, _ := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)
	var linkedEntries []*gap_investigator.LinkedEntry
	for _, e := range entries {
		if e.ActualPage != nil {
			linkedEntries = append(linkedEntries, &gap_investigator.LinkedEntry{
				DocID:      e.DocID,
				Title:      e.Title,
				Level:      e.Level,
				LevelName:  e.LevelName,
				ActualPage: *e.ActualPage,
			})
		}
	}

	var ag *agent.Agent

	// Check for saved agent state (job resume case)
	savedState := j.Book.GetAgentState(common.AgentTypeGapInvestigator, gap.Key)
	if savedState != nil && !savedState.Complete {
		// Resume existing agent
		if logger != nil {
			logger.Debug("resuming gap investigator agent from saved state",
				"agent_id", savedState.AgentID,
				"gap_key", gap.Key,
				"iteration", savedState.Iteration)
		}

		ag = agents.NewGapInvestigatorAgent(ctx, agents.GapInvestigatorConfig{
			Book:          j.Book,
			SystemPrompt:  j.GetPrompt(gap_investigator.PromptKey),
			Gap:           agentGap,
			LinkedEntries: linkedEntries,
			Debug:         j.Book.DebugAgents,
			JobID:         j.RecordID,
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
				logger.Warn("failed to restore gap investigator agent state, starting fresh",
					"gap_key", gap.Key,
					"error", err)
			}
			ag = nil
		}
	}

	// Create fresh agent if not restored
	if ag == nil {
		ag = agents.NewGapInvestigatorAgent(ctx, agents.GapInvestigatorConfig{
			Book:          j.Book,
			SystemPrompt:  j.GetPrompt(gap_investigator.PromptKey),
			Gap:           agentGap,
			LinkedEntries: linkedEntries,
			Debug:         j.Book.DebugAgents,
			JobID:         j.RecordID,
		})
	}

	// Build initial state (don't persist yet)
	exported, _ := ag.ExportState()
	initialState := &common.AgentState{
		AgentID:          exported.AgentID,
		AgentType:        common.AgentTypeGapInvestigator,
		EntryDocID:       gap.Key,
		Iteration:        exported.Iteration,
		Complete:         false,
		MessagesJSON:     exported.MessagesJSON,
		PendingToolCalls: exported.PendingToolCalls,
		ToolResults:      exported.ToolResults,
		ResultJSON:       "",
	}

	return ag, initialState
}

// createGapInvestigatorWorkUnit creates a gap investigator agent work unit.
// Used for single agent creation (e.g., retries). For batch creation, use createFinalizeGapWorkUnits.
func (j *Job) createGapInvestigatorWorkUnit(ctx context.Context, gap *common.FinalizeGap) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Create agent and initial state
	ag, initialState := j.createGapInvestigatorAgentWithState(ctx, gap)
	if ag == nil || initialState == nil {
		return nil
	}

	j.FinalizeGapAgents[gap.Key] = ag

	// Persist single agent state (uses sync write)
	if err := common.PersistAgentState(ctx, j.Book, initialState); err != nil {
		if logger != nil {
			logger.Warn("failed to persist gap investigator agent state",
				"gap_key", gap.Key,
				"error", err)
		}
	}
	j.Book.SetAgentState(initialState)

	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		return nil
	}

	jobUnits := j.convertGapAgentUnits(agentUnits, gap.Key)
	if len(jobUnits) == 0 {
		return nil
	}

	return &jobUnits[0]
}

// HandleFinalizeGapComplete processes gap investigator completion.
func (j *Job) HandleFinalizeGapComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	logger := svcctx.LoggerFrom(ctx)

	ag, ok := j.FinalizeGapAgents[info.FinalizeKey]
	if !ok {
		j.RemoveWorkUnit(result.WorkUnitID)
		j.Book.IncrementFinalizeGapsComplete()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistFinalizeProgressAsync(ctx, j.Book)
		return j.checkFinalizeValidateCompletion(ctx), nil
	}

	if !result.Success {
		if info.RetryCount < MaxFinalizeRetries {
			if logger != nil {
				logger.Warn("gap investigator failed, retrying",
					"gap_key", info.FinalizeKey,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			return j.retryFinalizeGapUnit(ctx, info)
		}
		j.Book.IncrementFinalizeGapsComplete()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistFinalizeProgressAsync(ctx, j.Book)
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("gap investigator permanently failed",
				"gap_key", info.FinalizeKey,
				"error", result.Error)
		}
		return j.checkFinalizeValidateCompletion(ctx), nil
	}

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)
		if err := j.checkpointAgentState(ctx, ag, common.AgentTypeGapInvestigator, info.FinalizeKey); err != nil {
			return nil, err
		}

		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			return j.convertGapAgentUnits(agentUnits, info.FinalizeKey), nil
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
		j.cleanupFinalizeGapAgentState(ctx, info.FinalizeKey)

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if gapResult, ok := agentResult.ToolResult.(*gap_investigator.Result); ok {
				writeResult, err := j.applyGapFix(ctx, info.FinalizeKey, gapResult)
				if err != nil {
					if logger != nil {
						logger.Warn("failed to apply gap fix", "error", err)
					}
				} else if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "TocEntry", writeResult.DocID, writeResult.CID); err != nil {
					if logger != nil {
						logger.Warn("failed to update metric output ref", "error", err)
					}
				}
				if gapResult.FixType == "add_entry" || gapResult.FixType == "correct_entry" {
					j.Book.IncrementFinalizeGapsFixes()
				}
			}
		}

		j.Book.IncrementFinalizeGapsComplete()
		// Persist progress (async - memory is authoritative during execution)
		common.PersistFinalizeProgressAsync(ctx, j.Book)
		delete(j.FinalizeGapAgents, info.FinalizeKey)
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	return j.checkFinalizeValidateCompletion(ctx), nil
}
