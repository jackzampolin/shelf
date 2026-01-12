package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	common_structure "github.com/jackzampolin/shelf/internal/jobs/common_structure/job"
	finalize_toc_job "github.com/jackzampolin/shelf/internal/jobs/finalize_toc/job"
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
	// Estimate book structure for back matter detection
	bookStructure := &toc_entry_finder.BookStructure{
		TotalPages:      j.Book.TotalPages,
		BackMatterStart: int(float64(j.Book.TotalPages) * 0.8),
		BackMatterTypes: "footnotes, bibliography, index",
	}

	// Create agent
	ag := agents.NewTocEntryFinderAgent(ctx, agents.TocEntryFinderConfig{
		Book:          j.Book,
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
	return common.PersistTocLinkState(ctx, j.TocDocID, &j.Book.TocLink)
}

// StartFinalizeTocInline creates and starts the finalize-toc sub-job inline.
// Returns work units to process. This replaces SubmitFinalizeTocJob.
func (j *Job) StartFinalizeTocInline(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Mark finalize as started to prevent duplicate starts
	if err := j.Book.TocFinalize.Start(); err != nil {
		if logger != nil {
			logger.Debug("finalize already started", "error", err)
		}
		return nil
	}
	common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)

	// Load linked entries for the finalize sub-job
	entries, err := common.LoadLinkedEntries(ctx, j.TocDocID)
	if err != nil {
		if logger != nil {
			logger.Error("failed to load linked entries for finalize",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.TocFinalize.Fail(MaxBookOpRetries)
		common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)
		return nil
	}

	// Create the finalize sub-job using our already-loaded book result
	loadResult := &common.LoadBookResult{
		Book:     j.Book,
		TocDocID: j.TocDocID,
	}
	j.FinalizeJob = finalize_toc_job.NewFromLoadResult(loadResult, entries)
	j.FinalizeJob.SetRecordID(j.RecordID) // Use parent job's record ID

	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("starting finalize-toc inline",
			"book_id", j.Book.BookID,
			"entries_count", len(entries),
			"linked_count", linkedCount)
	}

	// Start the finalize sub-job to get initial work units
	units, err := j.FinalizeJob.Start(ctx)
	if err != nil {
		if logger != nil {
			logger.Error("failed to start finalize sub-job",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.TocFinalize.Fail(MaxBookOpRetries)
		common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)
		return nil
	}

	// If finalize completed immediately (no work to do)
	if j.FinalizeJob.Done() {
		j.Book.TocFinalize.Complete()
		common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)
		if logger != nil {
			logger.Info("finalize-toc completed immediately (no work needed)",
				"book_id", j.Book.BookID)
		}
		// Continue to structure if ready
		return j.MaybeStartStructureInline(ctx)
	}

	// Register finalize work units in our tracker
	for _, unit := range units {
		j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizePattern,
			FinalizePhase: FinalizePhasePattern,
		})
	}

	return units
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

// HandleFinalizeComplete routes finalize work unit completion to the sub-job.
func (j *Job) HandleFinalizeComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	if j.FinalizeJob == nil {
		return nil, fmt.Errorf("finalize sub-job not initialized")
	}

	logger := svcctx.LoggerFrom(ctx)

	// Delegate to the finalize sub-job's OnComplete
	units, err := j.FinalizeJob.OnComplete(ctx, result)
	if err != nil {
		if logger != nil {
			logger.Error("finalize sub-job OnComplete failed",
				"book_id", j.Book.BookID,
				"error", err)
		}
		return nil, err
	}

	// Check if finalize is done
	if j.FinalizeJob.Done() {
		j.Book.TocFinalize.Complete()
		common.PersistTocFinalizeState(ctx, j.TocDocID, &j.Book.TocFinalize)
		if logger != nil {
			logger.Info("finalize-toc completed",
				"book_id", j.Book.BookID)
		}
		// Continue to structure if ready
		structureUnits := j.MaybeStartStructureInline(ctx)
		units = append(units, structureUnits...)
	}

	// Register new work units from finalize sub-job
	for _, unit := range units {
		// Determine unit type based on sub-job phase
		unitType := WorkUnitTypeFinalizePattern
		phase := FinalizePhasePattern
		if j.FinalizeJob != nil {
			// Get current phase from the finalize job status
			status, _ := j.FinalizeJob.Status(ctx)
			if p, ok := status["phase"]; ok {
				switch p {
				case "discover":
					unitType = WorkUnitTypeFinalizeDiscover
					phase = FinalizePhaseDiscover
				case "validate":
					unitType = WorkUnitTypeFinalizeGap
					phase = FinalizePhaseValidate
				}
			}
		}
		j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
			UnitType:      unitType,
			FinalizePhase: phase,
		})
	}

	return units, nil
}

// MaybeStartStructureInline starts the common-structure sub-job if ready.
// Returns work units to process.
func (j *Job) MaybeStartStructureInline(ctx context.Context) []jobs.WorkUnit {
	// Only start structure if finalize is complete and structure not yet started
	if !j.Book.TocFinalize.IsComplete() || !j.Book.Structure.CanStart() {
		return nil
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("starting common-structure inline",
			"book_id", j.Book.BookID)
	}

	// Mark structure as started
	if err := j.Book.Structure.Start(); err != nil {
		if logger != nil {
			logger.Debug("structure already started", "error", err)
		}
		return nil
	}
	common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)

	// Load linked entries (finalized after finalize_toc)
	linkedEntries, err := common.LoadLinkedEntries(ctx, j.TocDocID)
	if err != nil {
		if logger != nil {
			logger.Error("failed to load linked entries for structure",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.Structure.Fail(MaxBookOpRetries)
		common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)
		return nil
	}

	// Create the structure sub-job using our already-loaded book
	loadResult := &common.LoadBookResult{
		Book:     j.Book,
		TocDocID: j.TocDocID,
	}
	j.StructureJob = common_structure.NewFromLoadResult(loadResult, linkedEntries)
	j.StructureJob.SetRecordID(j.RecordID) // Use parent job's record ID

	// Start the structure sub-job to get initial work units
	units, err := j.StructureJob.Start(ctx)
	if err != nil {
		if logger != nil {
			logger.Error("failed to start structure sub-job",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.Structure.Fail(MaxBookOpRetries)
		common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)
		return nil
	}

	// If structure completed immediately (no work to do)
	if j.StructureJob.Done() {
		j.Book.Structure.Complete()
		common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)
		if logger != nil {
			logger.Info("common-structure completed immediately (no work needed)",
				"book_id", j.Book.BookID)
		}
		return nil
	}

	// Register structure work units in our tracker
	for _, unit := range units {
		j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
			UnitType:       WorkUnitTypeStructureClassify,
			StructurePhase: StructurePhaseClassify,
		})
	}

	if logger != nil {
		logger.Info("common-structure started",
			"book_id", j.Book.BookID,
			"work_units", len(units))
	}

	return units
}

// HandleStructureComplete routes structure work unit completion to the sub-job.
func (j *Job) HandleStructureComplete(ctx context.Context, result jobs.WorkResult, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	if j.StructureJob == nil {
		return nil, fmt.Errorf("structure sub-job not initialized")
	}

	logger := svcctx.LoggerFrom(ctx)

	// Delegate to the structure sub-job's OnComplete
	units, err := j.StructureJob.OnComplete(ctx, result)
	if err != nil {
		if logger != nil {
			logger.Error("structure sub-job OnComplete failed",
				"book_id", j.Book.BookID,
				"error", err)
		}
		return nil, err
	}

	// Check if structure is done
	if j.StructureJob.Done() {
		j.Book.Structure.Complete()
		common.PersistStructureState(ctx, j.Book.BookID, &j.Book.Structure)
		if logger != nil {
			logger.Info("common-structure completed",
				"book_id", j.Book.BookID)
		}
	}

	// Register new work units from structure sub-job
	for _, unit := range units {
		// Determine unit type based on sub-job phase
		unitType := WorkUnitTypeStructureClassify
		phase := StructurePhaseClassify
		if j.StructureJob != nil {
			status, _ := j.StructureJob.Status(ctx)
			if p, ok := status["phase"]; ok {
				switch p {
				case "polish":
					unitType = WorkUnitTypeStructurePolish
					phase = StructurePhasePolish
				}
			}
		}
		j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
			UnitType:       unitType,
			StructurePhase: phase,
		})
	}

	return units, nil
}
