package job

import (
	"context"
	"fmt"
	"strings"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateDiscoverWorkUnits creates work units for all entries to discover.
func (j *Job) CreateDiscoverWorkUnits(ctx context.Context) ([]jobs.WorkUnit, error) {
	var units []jobs.WorkUnit

	for _, entry := range j.EntriesToFind {
		unit := j.CreateChapterFinderWorkUnit(ctx, entry)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units, nil
}

// CreateChapterFinderWorkUnit creates a chapter finder agent work unit.
func (j *Job) CreateChapterFinderWorkUnit(ctx context.Context, entry *EntryToFind) *jobs.WorkUnit {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil
	}

	// Convert excluded ranges for the agent
	var excludedRanges []chapter_finder.ExcludedRange
	if j.PatternResult != nil {
		for _, ex := range j.PatternResult.Excluded {
			excludedRanges = append(excludedRanges, chapter_finder.ExcludedRange{
				StartPage: ex.StartPage,
				EndPage:   ex.EndPage,
				Reason:    ex.Reason,
			})
		}
	}

	// Convert entry for agent
	agentEntry := &chapter_finder.EntryToFind{
		LevelName:        entry.LevelName,
		Identifier:       entry.Identifier,
		HeadingFormat:    entry.HeadingFormat,
		ExpectedNearPage: entry.ExpectedNearPage,
		SearchRangeStart: entry.SearchRangeStart,
		SearchRangeEnd:   entry.SearchRangeEnd,
	}

	// Create agent
	ag := agents.NewChapterFinderAgent(ctx, agents.ChapterFinderConfig{
		BookID:         j.Book.BookID,
		TotalPages:     j.Book.TotalPages,
		DefraClient:    defraClient,
		HomeDir:        j.Book.HomeDir,
		SystemPrompt:   j.GetPrompt(chapter_finder.PromptKey),
		Entry:          agentEntry,
		ExcludedRanges: excludedRanges,
		Debug:          j.Book.DebugAgents,
		JobID:          j.RecordID,
	})

	// Store agent for later reference
	j.DiscoverAgents[entry.Key] = ag

	// Get first work unit
	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		return nil
	}

	// Convert and return first work unit
	jobUnits := j.convertDiscoverAgentUnits(agentUnits, entry.Key)
	if len(jobUnits) == 0 {
		return nil
	}

	return &jobUnits[0]
}

// HandleDiscoverResult processes chapter finder agent work unit completion.
func (j *Job) HandleDiscoverResult(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	ag, ok := j.DiscoverAgents[info.EntryKey]
	if !ok {
		return nil, fmt.Errorf("agent not found for entry %s", info.EntryKey)
	}

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)

		// Execute tool loop
		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			// More work to do
			return j.convertDiscoverAgentUnits(agentUnits, info.EntryKey), nil
		}
	}

	// Check if agent is done
	if ag.IsDone() {
		// Save agent log if debug enabled
		if err := ag.SaveLog(ctx); err != nil {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Info("failed to save agent log", "error", err)
			}
		}

		agentResult := ag.Result()
		if agentResult != nil && agentResult.Success {
			if finderResult, ok := agentResult.ToolResult.(*chapter_finder.Result); ok {
				// Save discovered entry to DefraDB
				if err := j.SaveDiscoveredEntry(ctx, info.EntryKey, finderResult); err != nil {
					return nil, fmt.Errorf("failed to save discovered entry: %w", err)
				}
				if finderResult.ScanPage != nil && *finderResult.ScanPage > 0 {
					j.EntriesFound++
				}
			}
		}

		j.EntriesComplete++
		delete(j.DiscoverAgents, info.EntryKey)
	}

	return nil, nil
}

// SaveDiscoveredEntry creates a new TocEntry for a discovered chapter.
func (j *Job) SaveDiscoveredEntry(ctx context.Context, entryKey string, result *chapter_finder.Result) error {
	if result.ScanPage == nil || *result.ScanPage == 0 {
		return nil // No page found
	}

	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	// Find the entry to get metadata
	var entry *EntryToFind
	for _, e := range j.EntriesToFind {
		if e.Key == entryKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return fmt.Errorf("entry not found: %s", entryKey)
	}

	// Get page document ID
	pageDocID, err := j.getPageDocID(ctx, *result.ScanPage)
	if err != nil {
		return fmt.Errorf("failed to get page doc ID: %w", err)
	}

	// Calculate sort order (insert between existing entries)
	sortOrder := j.calculateSortOrder(*result.ScanPage)

	// Build title from entry metadata (chapter_finder.Result doesn't have Title)
	title := fmt.Sprintf("%s %s", strings.Title(entry.LevelName), entry.Identifier)

	// Create new TocEntry
	newEntry := map[string]any{
		"toc_id":       j.TocDocID,
		"entry_number": entry.Identifier,
		"title":        title,
		"level":        entry.Level,
		"level_name":   entry.LevelName,
		"sort_order":   sortOrder,
		"source":       "discovered",
	}

	if pageDocID != "" {
		newEntry["actual_page_id"] = pageDocID
	}

	sink.Send(defra.WriteOp{
		Collection: "TocEntry",
		Document:   newEntry,
		Op:         defra.OpCreate,
	})

	return nil
}

// calculateSortOrder determines sort order for a new entry based on page.
func (j *Job) calculateSortOrder(page int) int {
	// Find entries before and after this page
	var beforeOrder, afterOrder int
	beforeFound, afterFound := false, false

	for _, entry := range j.LinkedEntries {
		if entry.ActualPage == nil {
			continue
		}
		if *entry.ActualPage < page {
			if !beforeFound || entry.SortOrder > beforeOrder {
				beforeOrder = entry.SortOrder
				beforeFound = true
			}
		} else if *entry.ActualPage > page {
			if !afterFound || entry.SortOrder < afterOrder {
				afterOrder = entry.SortOrder
				afterFound = true
			}
		}
	}

	if beforeFound && afterFound {
		// Insert between
		return (beforeOrder + afterOrder) / 2
	} else if beforeFound {
		// After the last entry
		return beforeOrder + 100
	} else if afterFound {
		// Before the first entry
		return afterOrder - 100
	}

	// Default
	return page * 100
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

	return "", nil
}

// convertDiscoverAgentUnits converts agent work units to job work units.
func (j *Job) convertDiscoverAgentUnits(agentUnits []agent.WorkUnit, entryKey string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     j.Type(),
		ItemKey:   fmt.Sprintf("discover_%s", entryKey),
		PromptKey: chapter_finder.PromptKey,
		PromptCID: j.GetPromptCID(chapter_finder.PromptKey),
		BookID:    j.Book.BookID,
	})

	// Register work units
	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{
			UnitType: WorkUnitTypeDiscover,
			Phase:    PhaseDiscover,
			EntryKey: entryKey,
		})
	}

	return jobUnits
}

// retryDiscoverUnit creates a retry work unit for a failed discovery.
func (j *Job) retryDiscoverUnit(ctx context.Context, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	// Find the entry for this key
	var entry *EntryToFind
	for _, e := range j.EntriesToFind {
		if e.Key == info.EntryKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return nil, nil
	}

	// Remove old agent
	delete(j.DiscoverAgents, info.EntryKey)

	// Create new work unit
	unit := j.CreateChapterFinderWorkUnit(ctx, entry)
	if unit != nil {
		// Update the registered info with incremented retry count
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeDiscover,
			Phase:      PhaseDiscover,
			EntryKey:   info.EntryKey,
			RetryCount: info.RetryCount + 1,
		})
		return []jobs.WorkUnit{*unit}, nil
	}

	return nil, nil
}
