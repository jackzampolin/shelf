package job

import (
	"context"
	"fmt"
	"sort"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	gap_investigator "github.com/jackzampolin/shelf/internal/agents/gap_investigator"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MinGapSize is the minimum number of pages to consider a gap significant.
const MinGapSize = 15

// FindGaps identifies gaps in page coverage between consecutive entries.
func (j *Job) FindGaps(ctx context.Context) error {
	// Reload linked entries to include any discovered entries
	if err := j.reloadLinkedEntries(ctx); err != nil {
		return err
	}

	// Sort entries by actual page
	sortedEntries := make([]*LinkedTocEntry, 0, len(j.LinkedEntries))
	for _, e := range j.LinkedEntries {
		if e.ActualPage != nil {
			sortedEntries = append(sortedEntries, e)
		}
	}
	sort.Slice(sortedEntries, func(i, k int) bool {
		return *sortedEntries[i].ActualPage < *sortedEntries[k].ActualPage
	})

	// Find gaps
	j.Gaps = nil

	// Check gap from body start to first entry
	if len(sortedEntries) > 0 {
		first := sortedEntries[0]
		if *first.ActualPage-j.Book.BodyStart > MinGapSize {
			j.Gaps = append(j.Gaps, &Gap{
				Key:            fmt.Sprintf("gap_%d_%d", j.Book.BodyStart, *first.ActualPage-1),
				StartPage:      j.Book.BodyStart,
				EndPage:        *first.ActualPage - 1,
				Size:           *first.ActualPage - j.Book.BodyStart,
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
			// Check if this gap is in an excluded range
			if j.isPageExcluded(*curr.ActualPage + 1) {
				continue
			}

			j.Gaps = append(j.Gaps, &Gap{
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
		if j.Book.BodyEnd-*last.ActualPage > MinGapSize && !j.isPageExcluded(*last.ActualPage+1) {
			j.Gaps = append(j.Gaps, &Gap{
				Key:            fmt.Sprintf("gap_%d_%d", *last.ActualPage+1, j.Book.BodyEnd),
				StartPage:      *last.ActualPage + 1,
				EndPage:        j.Book.BodyEnd,
				Size:           j.Book.BodyEnd - *last.ActualPage,
				PrevEntryTitle: last.Title,
				PrevEntryPage:  *last.ActualPage,
			})
		}
	}

	return nil
}

// isPageExcluded checks if a page is in an excluded range.
func (j *Job) isPageExcluded(page int) bool {
	if j.PatternResult == nil {
		return false
	}
	for _, ex := range j.PatternResult.Excluded {
		if page >= ex.StartPage && page <= ex.EndPage {
			return true
		}
	}
	return false
}

// reloadLinkedEntries reloads linked entries from DefraDB (to include discoveries).
func (j *Job) reloadLinkedEntries(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		TocEntry(filter: {toc_id: {_eq: "%s"}}, order: {sort_order: ASC}) {
			_docID
			entry_number
			title
			level
			level_name
			sort_order
			actual_page {
				_docID
				page_num
			}
		}
	}`, j.TocDocID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	rawEntries, ok := resp.Data["TocEntry"].([]any)
	if !ok {
		return nil
	}

	j.LinkedEntries = nil
	for _, e := range rawEntries {
		entry, ok := e.(map[string]any)
		if !ok {
			continue
		}

		le := &LinkedTocEntry{}
		if docID, ok := entry["_docID"].(string); ok {
			le.DocID = docID
		}
		if entryNum, ok := entry["entry_number"].(string); ok {
			le.EntryNumber = entryNum
		}
		if title, ok := entry["title"].(string); ok {
			le.Title = title
		}
		if level, ok := entry["level"].(float64); ok {
			le.Level = int(level)
		}
		if levelName, ok := entry["level_name"].(string); ok {
			le.LevelName = levelName
		}
		if sortOrder, ok := entry["sort_order"].(float64); ok {
			le.SortOrder = int(sortOrder)
		}

		// Extract actual_page link
		if actualPage, ok := entry["actual_page"].(map[string]any); ok {
			if pageDocID, ok := actualPage["_docID"].(string); ok {
				le.ActualPageDocID = pageDocID
			}
			if pageNum, ok := actualPage["page_num"].(float64); ok {
				pn := int(pageNum)
				le.ActualPage = &pn
			}
		}

		if le.DocID != "" {
			j.LinkedEntries = append(j.LinkedEntries, le)
		}
	}

	return nil
}

// CreateGapWorkUnits creates work units for all gaps to investigate.
func (j *Job) CreateGapWorkUnits(ctx context.Context) ([]jobs.WorkUnit, error) {
	var units []jobs.WorkUnit

	for _, gap := range j.Gaps {
		unit := j.CreateGapInvestigatorWorkUnit(ctx, gap)
		if unit != nil {
			units = append(units, *unit)
		}
	}

	return units, nil
}

// CreateGapInvestigatorWorkUnit creates a gap investigator agent work unit.
func (j *Job) CreateGapInvestigatorWorkUnit(ctx context.Context, gap *Gap) *jobs.WorkUnit {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil
	}

	// Convert gap for agent
	agentGap := &gap_investigator.GapInfo{
		StartPage:      gap.StartPage,
		EndPage:        gap.EndPage,
		Size:           gap.Size,
		PrevEntryTitle: gap.PrevEntryTitle,
		PrevEntryPage:  gap.PrevEntryPage,
		NextEntryTitle: gap.NextEntryTitle,
		NextEntryPage:  gap.NextEntryPage,
	}

	// Convert linked entries for agent
	var linkedEntries []*gap_investigator.LinkedEntry
	for _, e := range j.LinkedEntries {
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

	// Create agent
	ag := agents.NewGapInvestigatorAgent(ctx, agents.GapInvestigatorConfig{
		BookID:        j.Book.BookID,
		TotalPages:    j.Book.TotalPages,
		DefraClient:   defraClient,
		HomeDir:       j.Book.HomeDir,
		SystemPrompt:  j.GetPrompt(gap_investigator.PromptKey),
		Gap:           agentGap,
		LinkedEntries: linkedEntries,
		BodyStart:     j.Book.BodyStart,
		BodyEnd:       j.Book.BodyEnd,
		Debug:         j.Book.DebugAgents,
		JobID:         j.RecordID,
	})

	// Store agent for later reference
	j.GapAgents[gap.Key] = ag

	// Get first work unit
	agentUnits := agents.ExecuteToolLoop(ctx, ag)
	if len(agentUnits) == 0 {
		return nil
	}

	// Convert and return first work unit
	jobUnits := j.convertGapAgentUnits(agentUnits, gap.Key)
	if len(jobUnits) == 0 {
		return nil
	}

	return &jobUnits[0]
}

// HandleGapResult processes gap investigator agent work unit completion.
func (j *Job) HandleGapResult(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	ag, ok := j.GapAgents[info.GapKey]
	if !ok {
		return nil, fmt.Errorf("agent not found for gap %s", info.GapKey)
	}

	// Handle LLM result
	if result.ChatResult != nil {
		ag.HandleLLMResult(result.ChatResult)

		// Execute tool loop
		agentUnits := agents.ExecuteToolLoop(ctx, ag)
		if len(agentUnits) > 0 {
			// More work to do
			return j.convertGapAgentUnits(agentUnits, info.GapKey), nil
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
			if gapResult, ok := agentResult.ToolResult.(*gap_investigator.Result); ok {
				// Apply the fix
				if err := j.ApplyGapFix(ctx, info.GapKey, gapResult); err != nil {
					return nil, fmt.Errorf("failed to apply gap fix: %w", err)
				}
				if gapResult.FixType == "add_entry" || gapResult.FixType == "correct_entry" {
					j.GapsFixes++
				}
			}
		}

		j.GapsComplete++
		delete(j.GapAgents, info.GapKey)
	}

	return nil, nil
}

// ApplyGapFix applies a gap fix to DefraDB.
func (j *Job) ApplyGapFix(ctx context.Context, gapKey string, result *gap_investigator.Result) error {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return fmt.Errorf("defra sink not in context")
	}

	switch result.FixType {
	case "add_entry":
		if result.ScanPage == 0 {
			return nil
		}

		// Get page document ID
		pageDocID, err := j.getPageDocID(ctx, result.ScanPage)
		if err != nil {
			return fmt.Errorf("failed to get page doc ID: %w", err)
		}

		// Calculate sort order
		sortOrder := j.calculateSortOrder(result.ScanPage)

		// Create new TocEntry
		newEntry := map[string]any{
			"toc_id":     j.TocDocID,
			"title":      result.Title,
			"level":      result.Level,
			"level_name": result.LevelName,
			"sort_order": sortOrder,
			"source":     "validated",
		}

		if pageDocID != "" {
			newEntry["actual_page_id"] = pageDocID
		}

		sink.Send(defra.WriteOp{
			Collection: "TocEntry",
			Document:   newEntry,
			Op:         defra.OpCreate,
		})

	case "correct_entry":
		if result.EntryDocID == "" || result.ScanPage == 0 {
			return nil
		}

		// Get page document ID
		pageDocID, err := j.getPageDocID(ctx, result.ScanPage)
		if err != nil {
			return fmt.Errorf("failed to get page doc ID: %w", err)
		}

		if pageDocID != "" {
			sink.Send(defra.WriteOp{
				Collection: "TocEntry",
				DocID:      result.EntryDocID,
				Document: map[string]any{
					"actual_page_id": pageDocID,
				},
				Op: defra.OpUpdate,
			})
		}

	case "flag_for_review":
		// Log for manual review but don't modify anything
		logger := svcctx.LoggerFrom(ctx)
		if logger != nil {
			logger.Info("gap flagged for review",
				"gap_key", gapKey,
				"reasoning", result.Reasoning)
		}

	case "no_fix_needed":
		// Nothing to do
	}

	return nil
}

// convertGapAgentUnits converts agent work units to job work units.
func (j *Job) convertGapAgentUnits(agentUnits []agent.WorkUnit, gapKey string) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     j.Type(),
		ItemKey:   fmt.Sprintf("gap_%s", gapKey),
		PromptKey: gap_investigator.PromptKey,
		PromptCID: j.GetPromptCID(gap_investigator.PromptKey),
		BookID:    j.Book.BookID,
	})

	// Register work units
	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{
			UnitType: WorkUnitTypeGap,
			Phase:    PhaseValidate,
			GapKey:   gapKey,
		})
	}

	return jobUnits
}

// retryGapUnit creates a retry work unit for a failed gap investigation.
func (j *Job) retryGapUnit(ctx context.Context, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	// Find the gap for this key
	var gap *Gap
	for _, g := range j.Gaps {
		if g.Key == info.GapKey {
			gap = g
			break
		}
	}
	if gap == nil {
		return nil, nil
	}

	// Remove old agent
	delete(j.GapAgents, info.GapKey)

	// Create new work unit
	unit := j.CreateGapInvestigatorWorkUnit(ctx, gap)
	if unit != nil {
		// Update the registered info with incremented retry count
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeGap,
			Phase:      PhaseValidate,
			GapKey:     info.GapKey,
			RetryCount: info.RetryCount + 1,
		})
		return []jobs.WorkUnit{*unit}, nil
	}

	return nil, nil
}
