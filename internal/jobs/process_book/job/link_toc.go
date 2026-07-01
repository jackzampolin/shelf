package job

import (
	"context"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

const maxConcurrentLinkTocEntries = 8

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

// PersistTocLinkState persists ToC link state to DefraDB (async - memory is authoritative).
func (j *Job) PersistTocLinkState(ctx context.Context) {
	common.PersistOpStateAsync(ctx, j.Book, common.OpTocLink)
}
