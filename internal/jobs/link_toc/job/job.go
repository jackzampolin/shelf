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

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	// Handle force restart - reset state if requested
	if j.Force && j.Book.TocLink.IsComplete() {
		if logger != nil {
			logger.Info("force restart requested, resetting link toc state", "book_id", j.Book.BookID)
		}
		j.Book.TocLink.Reset()
		j.PersistTocLinkState(ctx)
	}

	// Check if already complete
	if j.Book.TocLink.IsComplete() {
		if logger != nil {
			logger.Info("link toc job already complete", "book_id", j.Book.BookID)
		}
		j.IsDone = true
		return nil, nil
	}

	// Crash recovery: reset any started-but-incomplete entries
	// We'll just restart all uncompleted entries

	// Mark link as started
	if j.Book.TocLink.CanStart() {
		if err := j.Book.TocLink.Start(); err != nil {
			return nil, fmt.Errorf("failed to start link operation: %w", err)
		}
		j.PersistTocLinkState(ctx)
	}

	// No entries to process - we're done
	if len(j.Entries) == 0 {
		j.Book.TocLink.Complete()
		j.PersistTocLinkState(ctx)
		j.IsDone = true
		if logger != nil {
			logger.Info("link toc job complete - no entries to process", "book_id", j.Book.BookID)
		}
		return nil, nil
	}

	// Preload all pages ONCE before creating agents
	// This avoids O(N) preload calls when N agents each try to preload on first tool use
	if err := j.Book.PreloadPages(ctx, 1, j.Book.TotalPages); err != nil {
		if logger != nil {
			logger.Warn("failed to preload pages at job start",
				"book_id", j.Book.BookID,
				"total_pages", j.Book.TotalPages,
				"error", err)
		}
		// Continue anyway - agents will preload on demand
	} else if logger != nil {
		logger.Info("preloaded all pages for link toc job",
			"book_id", j.Book.BookID,
			"total_pages", j.Book.TotalPages)
	}

	// Create work units for all entries
	var units []jobs.WorkUnit
	for i, entry := range j.Entries {
		if logger != nil {
			logger.Debug("creating work unit for entry",
				"index", i,
				"entry_doc_id", entry.DocID,
				"title", entry.Title)
		}
		unit := j.CreateEntryFinderWorkUnit(ctx, entry)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	if logger != nil {
		logger.Info("link toc job started",
			"book_id", j.Book.BookID,
			"entries", len(j.Entries),
			"work_units", len(units))
	}

	// If no work units created, mark as done
	if len(units) == 0 {
		j.Book.TocLink.Complete()
		j.PersistTocLinkState(ctx)
		j.IsDone = true
	}

	return units, nil
}

func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	info, ok := j.GetWorkUnit(result.WorkUnitID)
	if !ok {
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Warn("received result for unknown work unit",
				"work_unit_id", result.WorkUnitID,
				"book_id", j.Book.BookID)
		}
		return nil, nil
	}

	logger := svcctx.LoggerFrom(ctx)

	if !result.Success {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("entry finder failed, retrying",
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			retryUnit := j.createRetryUnit(ctx, info)
			if retryUnit != nil {
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		// Permanent failure - mark entry as not found but continue
		j.EntriesComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("entry finder permanently failed",
				"entry_doc_id", info.EntryDocID,
				"error", result.Error)
		}
		j.CheckCompletion(ctx)
		return nil, nil
	}

	// Handle successful completion
	var newUnits []jobs.WorkUnit
	units, err := j.HandleEntryFinderComplete(ctx, result, info)
	if err != nil {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("entry finder handler failed, retrying",
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"error", err)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			retryUnit := j.createRetryUnit(ctx, info)
			if retryUnit != nil {
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		// Handler failed permanently - mark entry as done
		j.EntriesComplete++
		j.RemoveWorkUnit(result.WorkUnitID)
		if logger != nil {
			logger.Warn("entry finder handler permanently failed",
				"entry_doc_id", info.EntryDocID,
				"error", err)
		}
		j.CheckCompletion(ctx)
		return nil, nil
	}

	newUnits = append(newUnits, units...)
	j.RemoveWorkUnit(result.WorkUnitID)
	j.CheckCompletion(ctx)

	return newUnits, nil
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	return map[string]string{
		"book_id":          j.Book.BookID,
		"total_entries":    fmt.Sprintf("%d", len(j.Entries)),
		"entries_complete": fmt.Sprintf("%d", j.EntriesComplete),
		"entries_found":    fmt.Sprintf("%d", j.EntriesFound),
		"link_started":     fmt.Sprintf("%v", j.Book.TocLink.IsStarted()),
		"link_complete":    fmt.Sprintf("%v", j.Book.TocLink.IsComplete()),
		"done":             fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	return map[string]jobs.ProviderProgress{
		j.Book.TocProvider: {
			TotalExpected: len(j.Entries),
			Completed:     j.EntriesComplete,
		},
	}
}

// CheckCompletion checks if all entries have been processed.
func (j *Job) CheckCompletion(ctx context.Context) {
	if j.EntriesComplete >= len(j.Entries) {
		j.Book.TocLink.Complete()
		j.PersistTocLinkState(ctx)
		j.IsDone = true

		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Info("link toc job complete",
				"book_id", j.Book.BookID,
				"entries_total", len(j.Entries),
				"entries_found", j.EntriesFound)
		}
	}
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
		PageReader:    j.Book, // Cached page data access
		SystemPrompt:  j.GetPrompt(toc_entry_finder.PromptKey),
		Entry:         entry,
		BookStructure: bookStructure,
		Debug:         j.Book.DebugAgents,
		JobID:         j.RecordID,
	})

	// Store agent for later reference
	j.EntryAgents[entry.DocID] = ag

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
	jobUnits := j.convertEntryAgentUnits(agentUnits, entry.DocID)
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

// HandleEntryFinderComplete processes entry finder agent work unit completion.
func (j *Job) HandleEntryFinderComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	ag, ok := j.EntryAgents[info.EntryDocID]
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
			return j.convertEntryAgentUnits(agentUnits, info.EntryDocID), nil
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
				if entryResult.ScanPage != nil {
					j.EntriesFound++
				}
			}
		}

		j.EntriesComplete++
		delete(j.EntryAgents, info.EntryDocID)
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

// convertEntryAgentUnits converts agent work units to job work units.
func (j *Job) convertEntryAgentUnits(agentUnits []agent.WorkUnit, entryDocID string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     j.Type(),
		ItemKey:   fmt.Sprintf("entry_%s", entryDocID),
		PromptKey: toc_entry_finder.PromptKey,
		PromptCID: j.GetPromptCID(toc_entry_finder.PromptKey),
		BookID:    j.Book.BookID,
	})

	// Register work units
	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeEntryFinder,
			EntryDocID: entryDocID,
		})
	}

	return jobUnits
}

// PersistTocLinkState persists ToC link state to DefraDB.
func (j *Job) PersistTocLinkState(ctx context.Context) {
	if err := common.PersistTocLinkState(ctx, j.TocDocID, &j.Book.TocLink); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist toc link state",
				"toc_doc_id", j.TocDocID,
				"error", err)
		}
	}
}

// createRetryUnit creates a retry work unit for a failed operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo) *jobs.WorkUnit {
	// Find the entry for this doc ID
	var entry *toc_entry_finder.TocEntry
	for _, e := range j.Entries {
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
	delete(j.EntryAgents, info.EntryDocID)

	// Create new work unit
	unit := j.CreateEntryFinderWorkUnit(ctx, entry)
	if unit != nil {
		// Update the registered info with incremented retry count
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeEntryFinder,
			EntryDocID: info.EntryDocID,
			RetryCount: info.RetryCount + 1,
		})
	}

	return unit
}
