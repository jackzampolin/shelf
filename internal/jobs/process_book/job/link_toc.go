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

const maxConcurrentLinkTocEntries = 8
const maxLinkTocRetryHintBytes = 2000

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
	if total != len(j.LinkTocEntries) || done != 0 {
		// LinkTocEntries contains only entries that still need a page link, so
		// stale progress from an earlier full work set must not carry forward.
		j.Book.SetTocLinkProgress(len(j.LinkTocEntries), 0)
		// Persist progress (async - memory is authoritative during execution)
		common.PersistTocLinkProgressAsync(ctx, j.Book)
		if logger != nil {
			logger.Debug("reset ToC link progress for pending entries",
				"book_id", j.Book.BookID,
				"pending_entries", len(j.LinkTocEntries),
				"old_total", total,
				"old_done", done)
		}
	}

	return j.createMoreLinkTocWorkUnits(ctx, maxConcurrentLinkTocEntries)
}

func (j *Job) createMoreLinkTocWorkUnits(ctx context.Context, limit int) []jobs.WorkUnit {
	if limit <= 0 {
		return nil
	}

	logger := svcctx.LoggerFrom(ctx)

	// Phase 1: Create agents up to the local concurrency limit and collect
	// initial states without persisting individually.
	type agentWithState struct {
		entry        *toc_entry_finder.TocEntry
		agent        *agent.Agent
		initialState *common.AgentState
	}
	var agentsToCreate []agentWithState

	for _, entry := range j.LinkTocEntries {
		if len(agentsToCreate) >= limit {
			break
		}
		if entry == nil || entry.DocID == "" {
			continue
		}
		if _, active := j.LinkTocEntryAgents[entry.DocID]; active {
			continue
		}
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
		jobUnits := j.convertLinkTocAgentUnits(agentUnits, aws.entry.DocID, 0, "")
		if len(jobUnits) > 0 {
			units = append(units, jobUnits[0])
		}
	}

	return units
}

func (j *Job) fillLinkTocConcurrency(ctx context.Context) []jobs.WorkUnit {
	openSlots := maxConcurrentLinkTocEntries - len(j.LinkTocEntryAgents)
	if openSlots <= 0 {
		return nil
	}
	return j.createMoreLinkTocWorkUnits(ctx, openSlots)
}

func (j *Job) removeLinkTocEntry(entryDocID string) {
	if entryDocID == "" || len(j.LinkTocEntries) == 0 {
		return
	}
	for i, entry := range j.LinkTocEntries {
		if entry != nil && entry.DocID == entryDocID {
			j.LinkTocEntries = append(j.LinkTocEntries[:i], j.LinkTocEntries[i+1:]...)
			return
		}
	}
}

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
	if savedState != nil && !savedState.Complete && hint == "" {
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

func (j *Job) tocEntryBookStructure(ctx context.Context, entry *toc_entry_finder.TocEntry) *toc_entry_finder.BookStructure {
	if j.Book.GetFinalizePatternResult() == nil {
		j.loadExistingPatternResults(ctx)
	}

	entries := j.tocEntriesForStructure(ctx)

	return &toc_entry_finder.BookStructure{
		TotalPages:         j.Book.TotalPages,
		BackMatterStart:    deriveBackMatterStart(j.Book.TotalPages, j.Book.GetFinalizePatternResult()),
		BackMatterTypes:    deriveBackMatterTypes(j.Book.GetFinalizePatternResult(), entries),
		TargetIsBackMatter: tocEntryIsBackMatter(entry, entries),
	}
}

func (j *Job) tocEntriesForStructure(ctx context.Context) []*toc_entry_finder.TocEntry {
	byDocID := make(map[string]*toc_entry_finder.TocEntry)
	add := func(entry *toc_entry_finder.TocEntry) {
		if entry == nil || entry.DocID == "" {
			return
		}
		if _, exists := byDocID[entry.DocID]; exists {
			return
		}
		byDocID[entry.DocID] = entry
	}

	for _, entry := range j.Book.GetTocEntries() {
		add(entry)
	}
	for _, entry := range j.LinkTocEntries {
		add(entry)
	}
	for _, entry := range j.loadTocEntriesForStructure(ctx) {
		add(entry)
	}

	entries := make([]*toc_entry_finder.TocEntry, 0, len(byDocID))
	for _, entry := range byDocID {
		entries = append(entries, entry)
	}
	return entries
}

func (j *Job) loadTocEntriesForStructure(ctx context.Context) []*toc_entry_finder.TocEntry {
	if j.Book == nil || j.TocDocID == "" {
		return nil
	}

	linkedEntries := j.Book.GetLinkedEntries()
	if len(linkedEntries) == 0 {
		loaded, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
		if err != nil {
			if logger := svcctx.LoggerFrom(ctx); logger != nil {
				logger.Debug("could not load full ToC sequence for structure context",
					"book_id", j.Book.BookID,
					"toc_doc_id", j.TocDocID,
					"error", err)
			}
			return nil
		}
		linkedEntries = loaded
	}

	entries := make([]*toc_entry_finder.TocEntry, 0, len(linkedEntries))
	for _, linked := range linkedEntries {
		if linked == nil || linked.DocID == "" {
			continue
		}
		entries = append(entries, &toc_entry_finder.TocEntry{
			DocID:             linked.DocID,
			EntryNumber:       linked.EntryNumber,
			Title:             linked.Title,
			Level:             linked.Level,
			LevelName:         linked.LevelName,
			PrintedPageNumber: linked.PrintedPageNumber,
			SortOrder:         linked.SortOrder,
		})
	}
	return entries
}

func deriveBackMatterStart(totalPages int, pattern *common.FinalizePatternResult) int {
	if pattern != nil {
		start := 0
		for _, excluded := range pattern.Excluded {
			if excluded.StartPage < 1 {
				continue
			}
			if totalPages > 0 && excluded.StartPage > totalPages {
				continue
			}
			if !excludedRangeLooksBackMatter(excluded, totalPages) {
				continue
			}
			if start == 0 || excluded.StartPage < start {
				start = excluded.StartPage
			}
		}
		if start > 0 {
			return start
		}
	}

	if totalPages <= 0 {
		return 0
	}
	start := int(float64(totalPages) * 0.9)
	if start < 1 {
		return 1
	}
	return start
}

func excludedRangeLooksBackMatter(excluded common.ExcludedRange, totalPages int) bool {
	if _, ok := backMatterLabelFromText(excluded.Reason); ok {
		return true
	}
	if totalPages <= 0 {
		return false
	}
	return excluded.StartPage >= int(float64(totalPages)*0.85)
}

func deriveBackMatterTypes(pattern *common.FinalizePatternResult, entries []*toc_entry_finder.TocEntry) string {
	var labels []string
	seen := make(map[string]bool)
	add := func(label string) {
		if label == "" || seen[label] {
			return
		}
		seen[label] = true
		labels = append(labels, label)
	}

	for _, entry := range entries {
		if label, ok := backMatterLabelFromText(entry.Title); ok {
			add(label)
		}
	}
	if pattern != nil {
		for _, excluded := range pattern.Excluded {
			if label, ok := backMatterLabelFromText(excluded.Reason); ok {
				add(label)
			}
		}
	}
	if len(labels) == 0 {
		labels = []string{"late notes", "appendices", "glossary", "index"}
	}
	return strings.Join(labels, ", ")
}

func tocEntryIsBackMatter(entry *toc_entry_finder.TocEntry, entries []*toc_entry_finder.TocEntry) bool {
	if entry == nil {
		return false
	}
	if _, ok := backMatterLabelFromText(entry.Title); ok {
		return true
	}

	firstBackMatterSort := 0
	for _, candidate := range entries {
		if candidate == nil {
			continue
		}
		if _, ok := backMatterLabelFromText(candidate.Title); !ok {
			continue
		}
		if candidate.SortOrder > 0 && (firstBackMatterSort == 0 || candidate.SortOrder < firstBackMatterSort) {
			firstBackMatterSort = candidate.SortOrder
		}
	}
	return firstBackMatterSort > 0 && entry.SortOrder >= firstBackMatterSort
}

func backMatterLabelFromText(text string) (string, bool) {
	lower := strings.ToLower(text)
	switch {
	case strings.Contains(lower, "acknowledg"):
		return "acknowledgments", true
	case strings.Contains(lower, "footnote"):
		return "footnotes", true
	case strings.Contains(lower, "endnote"):
		return "endnotes", true
	case strings.Contains(lower, "appendix") || strings.Contains(lower, "appendices"):
		return "appendices", true
	case strings.Contains(lower, "glossary"):
		return "glossary", true
	case strings.Contains(lower, "bibliograph"):
		return "bibliography", true
	case strings.Contains(lower, "references"):
		return "references", true
	case strings.Contains(lower, "index"):
		return "index", true
	case strings.Contains(lower, "back matter"):
		return "back matter", true
	default:
		return "", false
	}
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
				unit := j.createLinkTocRetryUnit(ctx, info, resultErr)
				if unit != nil {
					return []jobs.WorkUnit{*unit}, nil
				}
				// If we can't create retry unit, fall through to mark as failed
			}

			// Retries exhausted (or retry creation failed): skip this entry rather
			// than failing the whole book. It is counted as resolved (unlinked) so
			// the link stage can complete and downstream stages run.
			if logger != nil {
				logger.Warn("ToC entry finder failed after retries; skipping entry to keep the book processing",
					"book_id", j.Book.BookID,
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"max_retries", MaxBookOpRetries,
					"error", resultErr)
			}
			// fall through to the shared resolution bookkeeping below
		}

		// Shared resolution bookkeeping for a linked OR skipped entry. The caller
		// (OnComplete) completes the link stage via maybeCompleteTocLink once
		// done >= total.
		return j.resolveTocLinkEntry(ctx, info), nil
	}

	return nil, nil
}

// resolveTocLinkEntry performs the bookkeeping shared by a successfully linked
// entry and a skipped (unlinkable) one: it removes the entry's agent state,
// counts it as resolved against the link progress, drops it from the active set,
// and returns work units that refill the link concurrency window. Completion of
// the link stage (done >= total) is handled by the caller via maybeCompleteTocLink.
func (j *Job) resolveTocLinkEntry(ctx context.Context, info WorkUnitInfo) []jobs.WorkUnit {
	j.cleanupLinkTocAgentStateWithMode(ctx, info.EntryDocID, true)
	j.Book.IncrementTocLinkEntriesDone()
	// Persist progress (async - memory is authoritative during execution)
	common.PersistTocLinkProgressAsync(ctx, j.Book)
	delete(j.LinkTocEntryAgents, info.EntryDocID)
	j.removeLinkTocEntry(info.EntryDocID)
	return j.fillLinkTocConcurrency(ctx)
}

func firstString(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return values[0]
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

// cleanupLinkTocAgentState removes link ToC entry agent state after completion.
// Uses async delete to avoid blocking the critical path.
func (j *Job) cleanupLinkTocAgentState(ctx context.Context, entryDocID string) {
	j.cleanupLinkTocAgentStateWithMode(ctx, entryDocID, false)
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
// Cleans up old agent state and creates a fresh agent with feedback from the rejection.
func (j *Job) createLinkTocRetryUnit(ctx context.Context, info WorkUnitInfo, retryReason error) *jobs.WorkUnit {
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

	retryHint := appendLinkTocRetryHint(info.RetryHint, info.RetryCount, retryReason)

	// Create new work unit with fresh agent and carry retry metadata through
	// every future LLM unit produced by this agent.
	return j.createEntryFinderWorkUnit(ctx, entry, info.RetryCount+1, retryHint)
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
