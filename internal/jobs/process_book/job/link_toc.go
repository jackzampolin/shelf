package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/defra"
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
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("defra client not in context for entry finder",
				"book_id", j.Book.BookID,
				"entry_doc_id", entry.DocID)
		}
		return nil
	}

	// Estimate book structure for back matter detection
	bookStructure := &toc_entry_finder.BookStructure{
		TotalPages:      j.Book.TotalPages,
		BackMatterStart: int(float64(j.Book.TotalPages) * 0.8),
		BackMatterTypes: "footnotes, bibliography, index",
	}

	// Create agent
	ag := agents.NewTocEntryFinderAgent(ctx, agents.TocEntryFinderConfig{
		BookID:        j.Book.BookID,
		TotalPages:    j.Book.TotalPages,
		DefraClient:   defraClient,
		HomeDir:       j.Book.HomeDir,
		SystemPrompt:  j.GetPrompt(toc_entry_finder.PromptKey),
		Entry:         entry,
		BookStructure: bookStructure,
		Debug:         j.Book.DebugAgents,
		JobID:         j.RecordID,
	})

	// Store agent for later reference
	j.LinkTocEntryAgents[entry.DocID] = ag

	// Get first work unit
	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Debug("agent produced no work units",
				"book_id", j.Book.BookID,
				"entry_doc_id", entry.DocID)
		}
		return nil
	}

	// Convert and return first work unit
	jobUnits := j.convertLinkTocAgentUnits(agentUnits, entry.DocID)
	if len(jobUnits) == 0 {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
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

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)

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
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if entryResult, ok := agentResult.ToolResult.(*toc_entry_finder.Result); ok {
				// Update TocEntry with actual_page
				if err := j.SaveEntryResult(ctx, info.EntryDocID, entryResult); err != nil {
					return nil, fmt.Errorf("failed to save entry result: %w", err)
				}
			}
		}

		j.LinkTocEntriesDone++
		delete(j.LinkTocEntryAgents, info.EntryDocID)
	}

	return nil, nil
}

// SaveEntryResult updates a TocEntry with the found page.
func (j *Job) SaveEntryResult(ctx context.Context, entryDocID string, result *toc_entry_finder.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	update := map[string]any{}

	if result.ScanPage != nil {
		// Need to get the Page document ID for this scan page
		pageDocID, err := j.getPageDocID(ctx, *result.ScanPage)
		if err != nil {
			return fmt.Errorf("failed to get page doc ID: %w", err)
		}
		if pageDocID != "" {
			update["actual_page_id"] = pageDocID
		}
	}

	if len(update) > 0 {
		sink.Send(defra.WriteOp{
			Collection: "TocEntry",
			DocID:      entryDocID,
			Document:   update,
			Op:         defra.OpUpdate,
		})
	}

	return nil
}

// getPageDocID returns the Page document ID for a given page number.
func (j *Job) getPageDocID(ctx context.Context, pageNum int) (string, error) {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return "", fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}, page_num: {_eq: %d}}) {
			_docID
		}
	}`, j.Book.BookID, pageNum)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return "", err
	}

	if pages, ok := resp.Data["Page"].([]any); ok && len(pages) > 0 {
		if page, ok := pages[0].(map[string]any); ok {
			if docID, ok := page["_docID"].(string); ok {
				return docID, nil
			}
		}
	}

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Debug("page not found in database",
			"book_id", j.Book.BookID,
			"page_num", pageNum)
	}
	return "", nil
}

// convertLinkTocAgentUnits converts agent work units to job work units.
func (j *Job) convertLinkTocAgentUnits(agentUnits []agent.WorkUnit, entryDocID string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     j.Type(),
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
	return common.PersistTocLinkState(ctx, j.TocDocID, &j.Book.TocLink)
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
