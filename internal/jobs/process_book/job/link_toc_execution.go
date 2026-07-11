package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	toc_entry_finder_tools "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder/tools"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

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
			return j.convertLinkTocAgentUnits(agentUnits, info.EntryDocID, info.RetryCount, info.RetryHint), nil
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

		agentResult := ag.Result()

		entryResult, resultErr := validTocLinkResult(agentResult)
		agentSuccess := resultErr == nil
		if agentSuccess {
			entry := j.findLinkTocEntry(info.EntryDocID)
			if err := j.validateTocLinkEvidence(ctx, entry, *entryResult.ScanPage); err != nil {
				agentSuccess = false
				resultErr = err
			}
		}
		if agentSuccess {
			// Update TocEntry with actual_page using common utility.
			cid, err := common.SaveTocEntryResult(ctx, j.Book, info.EntryDocID, entryResult)
			if err != nil {
				return nil, fmt.Errorf("failed to save entry result: %w", err)
			}
			if cid == "" {
				agentSuccess = false
				resultErr = fmt.Errorf("agent found page %d but no TocEntry link was saved", *entryResult.ScanPage)
			} else {
				j.Book.SetTocCID(cid)
				if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "TocEntry", info.EntryDocID, cid); err != nil {
					if logger != nil {
						logger.Warn("failed to update metric output ref", "error", err)
					}
				}
			}
		} else if logger != nil && resultErr != nil {
			logger.Warn("ToC entry finder completed without a usable page link",
				"book_id", j.Book.BookID,
				"entry_doc_id", info.EntryDocID,
				"error", resultErr)
		}

		// If agent failed, retry or mark as failed.
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
				unit, err := j.createLinkTocRetryUnit(ctx, info, resultErr)
				if err != nil {
					return nil, err
				}
				return []jobs.WorkUnit{*unit}, nil
			}

			// Retries exhausted. Return the deterministic failure to OnComplete,
			// which persists an actionable entry failure and fails the link stage.
			// An unlinked entry must never be counted as resolved: doing so lets a
			// degraded book reach complete and hides the repair that is required.
			if logger != nil {
				logger.Warn("ToC entry finder failed after retries; failing closed",
					"book_id", j.Book.BookID,
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"max_retries", MaxBookOpRetries,
					"error", resultErr)
			}
			return nil, resultErr
		}

		// Successful links alone count as resolved. The caller (OnComplete)
		// completes the link stage via maybeCompleteTocLink once done >= total.
		return j.resolveTocLinkEntry(ctx, info), nil
	}

	return nil, nil
}

func (j *Job) persistFailedTocLinkEntry(ctx context.Context, info WorkUnitInfo, reason error) error {
	reasonText := "ToC entry link retry budget exhausted"
	if reason != nil && strings.TrimSpace(reason.Error()) != "" {
		reasonText = strings.TrimSpace(reason.Error())
	}
	retries := info.RetryCount
	if retries < MaxBookOpRetries {
		retries = MaxBookOpRetries
	}
	if err := common.PersistTocEntryLinkState(ctx, j.Book, info.EntryDocID, retries, true, reasonText); err != nil {
		return fmt.Errorf("persist terminal link failure for entry %s: %w", info.EntryDocID, err)
	}
	return nil
}

// failTocLinkEntry records the terminal entry failure and fails the aggregate
// ToC link stage. The scheduler then marks the job and book failed, leaving the
// entry available to the source-backed repair-toc-entry workflow.
func (j *Job) failTocLinkEntry(ctx context.Context, info WorkUnitInfo, reason error) error {
	if err := j.persistFailedTocLinkEntry(ctx, info, reason); err != nil {
		return err
	}
	j.markBookOpRetryExhausted(common.OpTocLink)
	if err := j.Book.PersistOpState(ctx, common.OpTocLink); err != nil {
		return fmt.Errorf("persist failed ToC link stage: %w", err)
	}
	j.cleanupLinkTocAgentStateWithMode(ctx, info.EntryDocID, true)
	delete(j.LinkTocEntryAgents, info.EntryDocID)
	j.removeLinkTocEntry(info.EntryDocID)

	reasonText := "ToC entry link retry budget exhausted"
	if reason != nil && strings.TrimSpace(reason.Error()) != "" {
		reasonText = strings.TrimSpace(reason.Error())
	}
	return fmt.Errorf("ToC entry %s failed after %d retries: %s", info.EntryDocID, info.RetryCount, reasonText)
}

// resolveTocLinkEntry performs bookkeeping for a successfully linked entry: it
// removes the entry's agent state, counts it as resolved against link progress,
// drops it from the active set, and refills the link concurrency window.
func (j *Job) resolveTocLinkEntry(ctx context.Context, info WorkUnitInfo) []jobs.WorkUnit {
	j.cleanupLinkTocAgentStateWithMode(ctx, info.EntryDocID, true)
	j.Book.IncrementTocLinkEntriesDone()
	// Persist progress (async - memory is authoritative during execution)
	common.PersistTocLinkProgressAsync(ctx, j.Book)
	delete(j.LinkTocEntryAgents, info.EntryDocID)
	j.removeLinkTocEntry(info.EntryDocID)
	return j.fillLinkTocConcurrency(ctx)
}

func (j *Job) findLinkTocEntry(entryDocID string) *toc_entry_finder.TocEntry {
	if entryDocID == "" {
		return nil
	}
	for _, entry := range j.LinkTocEntries {
		if entry != nil && entry.DocID == entryDocID {
			return entry
		}
	}
	for _, entry := range j.Book.GetTocEntries() {
		if entry != nil && entry.DocID == entryDocID {
			return entry
		}
	}
	return nil
}

func (j *Job) validateTocLinkEvidence(ctx context.Context, entry *toc_entry_finder.TocEntry, scanPage int) error {
	if entry == nil {
		return fmt.Errorf("cannot validate ToC link evidence without entry metadata")
	}
	if scanPage < 1 || scanPage > j.Book.TotalPages {
		return fmt.Errorf("agent returned scan_page %d outside book range 1-%d", scanPage, j.Book.TotalPages)
	}

	structure := j.tocEntryBookStructure(ctx, entry)
	backMatterStart := 0
	targetIsBackMatter := false
	backMatterTypes := ""
	if structure != nil {
		backMatterStart = structure.BackMatterStart
		targetIsBackMatter = structure.TargetIsBackMatter
		backMatterTypes = structure.BackMatterTypes
	}
	inBackMatter := backMatterStart > 0 && scanPage >= backMatterStart
	if inBackMatter && !targetIsBackMatter {
		return fmt.Errorf("agent returned back-matter page %d for non-back-matter target %q", scanPage, entry.Title)
	}

	toolset := toc_entry_finder_tools.New(toc_entry_finder_tools.Config{
		Book:               j.Book,
		Entry:              entry,
		BackMatterStart:    backMatterStart,
		BackMatterTypes:    backMatterTypes,
		TargetIsBackMatter: targetIsBackMatter,
	})
	_, rejection, err := toolset.ValidateCandidatePage(ctx, scanPage)
	if err != nil {
		return fmt.Errorf("cannot validate scan_page %d OCR evidence: %w", scanPage, err)
	}
	if rejection != "" {
		return fmt.Errorf("agent returned scan_page %d for %q: %s", scanPage, entry.Title, rejection)
	}
	return nil
}

func validTocLinkResult(agentResult *agent.Result) (*toc_entry_finder.Result, error) {
	if agentResult == nil {
		return nil, fmt.Errorf("agent returned no result")
	}
	if !agentResult.Success {
		if agentResult.Error != "" {
			return nil, fmt.Errorf("%s", agentResult.Error)
		}
		return nil, fmt.Errorf("agent failed")
	}
	entryResult, ok := agentResult.ToolResult.(*toc_entry_finder.Result)
	if !ok || entryResult == nil {
		return nil, fmt.Errorf("agent returned unexpected result type %T", agentResult.ToolResult)
	}
	if entryResult.ScanPage == nil {
		return nil, fmt.Errorf("agent completed without scan_page: %s", entryResult.Reasoning)
	}
	return entryResult, nil
}

// cleanupLinkTocAgentStateWithMode removes link ToC entry agent state with
// selectable delete behavior.
func (j *Job) cleanupLinkTocAgentStateWithMode(ctx context.Context, entryDocID string, syncDelete bool) {
	if syncDelete {
		// Retry and success paths must delete synchronously and by logical key:
		// a retry uses a fresh agent_id, so older duplicate rows for the same
		// entry must be removed before the next agent is persisted.
		if err := j.Book.DeleteAgentStateByKeys(ctx, common.AgentTypeTocEntryFinder, entryDocID); err != nil {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Warn("failed to delete toc entry finder agent state",
					"entry_doc_id", entryDocID,
					"error", err)
			}
		}
		return
	}

	existing := j.Book.GetAgentState(common.AgentTypeTocEntryFinder, entryDocID)
	if existing != nil && existing.AgentID != "" {
		// Async delete - fire and forget to avoid blocking the critical path.
		common.DeleteAgentStateByAgentIDAsync(ctx, existing.AgentID)
	}
	j.Book.RemoveAgentState(common.AgentTypeTocEntryFinder, entryDocID)
}

// convertLinkTocAgentUnits converts agent work units to job work units.
func (j *Job) convertLinkTocAgentUnits(agentUnits []agent.WorkUnit, entryDocID string, retryCount int, retryHint string) []jobs.WorkUnit {
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
			RetryCount: retryCount,
			RetryHint:  retryHint,
		})
	}

	return jobUnits
}

// StartFinalizeTocInline creates and starts the finalize phase inline.
// Returns work units to process. This is an alias to StartFinalizePhase for compatibility.
func (j *Job) StartFinalizeTocInline(ctx context.Context) []jobs.WorkUnit {
	return j.StartFinalizePhase(ctx)
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
