package job

import (
	"context"
	"fmt"
	"sort"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
	"github.com/jackzampolin/shelf/internal/types"
)

// MaxFinalizeRetries is the maximum number of retries for finalize operations.
const MaxFinalizeRetries = 3

// MinGapSize is the minimum number of pages to consider a gap significant.
const MinGapSize = 15

// PagePatternContext holds page pattern analysis data for enhanced ToC finalization.
// This is local to finalize phase execution.
type PagePatternContext struct {
	BodyStartPage   int
	BodyEndPage     int
	HasBoundaries   bool
	ChapterPatterns []types.DetectedChapter
}

// StartFinalizePhase initializes and starts the finalize phase.
// Returns the first work units to process.
func (j *Job) StartFinalizePhase(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Mark finalize as started
	if err := j.Book.TocFinalizeStart(); err != nil {
		if logger != nil {
			logger.Debug("finalize already started", "error", err)
		}
		return nil
	}
	// Use async persist: memory is already updated by TocFinalizeStart(),
	// fire-and-forget DB write removes latency from critical path
	j.Book.PersistOpStateAsync(ctx, common.OpTocFinalize)

	// Load linked entries (uses cache if available)
	entries, err := common.GetOrLoadLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		if logger != nil {
			logger.Error("failed to load linked entries for finalize",
				"book_id", j.Book.BookID,
				"error", err)
		}
		j.Book.TocFinalizeFail(MaxBookOpRetries)
		j.Book.PersistOpStateAsync(ctx, common.OpTocFinalize)
		return nil
	}

	// Build page pattern context
	j.FinalizePagePatternCtx = buildPagePatternContext(j.Book)

	// Set body range: prefer page pattern analysis, fall back to ToC entries, then full book
	if j.FinalizePagePatternCtx.HasBoundaries {
		j.Book.SetBodyRange(j.FinalizePagePatternCtx.BodyStartPage, j.FinalizePagePatternCtx.BodyEndPage)
	} else {
		var minPage, maxPage int
		for _, entry := range entries {
			if entry.ActualPage != nil {
				page := *entry.ActualPage
				if minPage == 0 || page < minPage {
					minPage = page
				}
				if page > maxPage {
					maxPage = page
				}
			}
		}
		if minPage > 0 && maxPage > 0 {
			j.Book.SetBodyRange(minPage, maxPage)
		} else {
			j.Book.SetBodyRange(1, j.Book.TotalPages)
		}
	}

	// Set phase and persist async for crash recovery
	// Memory is updated by SetFinalizePhase, DB write is fire-and-forget
	j.Book.SetFinalizePhase(FinalizePhasePattern)
	j.Book.PersistFinalizePhaseAsync(ctx, FinalizePhasePattern)

	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("starting finalize phase",
			"book_id", j.Book.BookID,
			"entries_count", len(entries),
			"linked_count", linkedCount,
			"phase", FinalizePhasePattern)
	}

	// Check if pattern results already exist from a previous attempt (crash recovery).
	// This avoids re-doing the pattern analysis LLM call when finalize was retried
	// after a crash during discover or validate phase.
	if j.loadExistingPatternResults(ctx) {
		if logger != nil {
			logger.Debug("reusing existing pattern analysis results from previous attempt",
				"book_id", j.Book.BookID,
				"entries_to_find", j.Book.GetEntriesToFindCount())
		}
		return j.transitionToFinalizeDiscover(ctx)
	}

	// Create pattern analysis work unit
	unit, err := j.CreateFinalizePatternWorkUnit(ctx)
	if err != nil {
		if logger != nil {
			logger.Error("failed to create pattern work unit", "error", err)
		}
		return j.transitionToFinalizeDiscover(ctx)
	}

	if unit == nil {
		// No work to do - skip to completion
		return j.completeFinalizePhase(ctx)
	}

	return []jobs.WorkUnit{*unit}
}

// transitionToFinalizeValidate moves to the validate phase.
func (j *Job) transitionToFinalizeValidate(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Set phase and persist for crash recovery (async - memory is authoritative)
	j.Book.SetFinalizePhase(FinalizePhaseValidate)
	common.PersistFinalizePhaseAsync(ctx, j.Book, FinalizePhaseValidate)

	// Skip gap investigation if pattern analysis found no missing entries
	// Gaps between chapters are normal chapter content, not missing ToC entries
	if j.Book.GetEntriesToFindCount() == 0 {
		if logger != nil {
			logger.Debug("skipping gap investigation; pattern analysis found no missing entries",
				"book_id", j.Book.BookID)
		}
		return j.completeFinalizePhase(ctx)
	}

	// Find gaps in page coverage
	if err := j.findFinalizeGaps(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to find gaps", "error", err)
		}
	}

	// Set gaps total for progress tracking
	gapsCount := j.Book.GetFinalizeGapsCount()
	j.Book.SetFinalizeGapsTotal(gapsCount)

	if logger != nil {
		logger.Debug("transitioning to validate phase",
			"book_id", j.Book.BookID,
			"gaps", gapsCount)
	}

	// Persist progress with totals (async - memory is authoritative)
	common.PersistFinalizeProgressAsync(ctx, j.Book)

	if gapsCount == 0 {
		return j.completeFinalizePhase(ctx)
	}

	return j.createFinalizeGapWorkUnits(ctx)
}

// checkFinalizeValidateCompletion checks if validate phase is complete.
func (j *Job) checkFinalizeValidateCompletion(ctx context.Context) []jobs.WorkUnit {
	_, _, gapsComplete, _ := j.Book.GetFinalizeProgress()
	if gapsComplete >= j.Book.GetFinalizeGapsCount() {
		return j.completeFinalizePhase(ctx)
	}
	return nil
}

// completeFinalizePhase marks finalize as complete and transitions to structure.
func (j *Job) completeFinalizePhase(ctx context.Context) []jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Re-sort all TocEntries by actual_page
	if err := j.resortEntriesByPage(ctx); err != nil {
		if logger != nil {
			logger.Warn("failed to re-sort entries by page", "error", err)
		}
	}

	// For critical completion operations: sync write BEFORE updating memory.
	// This ensures memory and DB stay consistent - if write fails, memory is unchanged.
	// Phase is set first since it's part of the completion state.
	j.Book.SetFinalizePhase(FinalizePhaseDone)

	// Sync write for completion - must succeed before updating memory
	// Retry with backoff to handle transient failures (without this, job hangs with 0 pending units)
	var persistErr error
	for attempt := 0; attempt < 3; attempt++ {
		if _, persistErr = common.PersistOpComplete(ctx, j.Book, common.OpTocFinalize); persistErr == nil {
			break
		}
		if logger != nil {
			logger.Warn("failed to persist finalize completion, retrying",
				"attempt", attempt+1,
				"error", persistErr)
		}
		// Brief backoff between retries
		select {
		case <-ctx.Done():
			persistErr = ctx.Err()
			break
		case <-time.After(100 * time.Millisecond * time.Duration(attempt+1)):
		}
	}

	if persistErr != nil {
		if logger != nil {
			logger.Error("failed to persist finalize completion after retries - marking as failed",
				"error", persistErr)
		}
		// Revert phase and mark as permanently failed so job can complete with errors
		j.Book.SetFinalizePhase(FinalizePhaseValidate)
		j.Book.TocFinalizeFail(0) // Mark as failed immediately (0 = exceeded max retries)
		return nil
	}

	// NOW mark complete in memory after successful DB write
	j.Book.TocFinalizeComplete()

	// Fire async phase persist after completion is confirmed
	common.PersistFinalizePhaseAsync(ctx, j.Book, FinalizePhaseDone)

	if logger != nil {
		_, entriesFound, _, gapsFixes := j.Book.GetFinalizeProgress()
		logger.Info("finalize phase complete",
			"book_id", j.Book.BookID,
			"entries_found", entriesFound,
			"gaps_fixed", gapsFixes)
	}

	// Continue to structure
	return j.MaybeStartStructureInline(ctx)
}

type candidateHeading struct {
	PageNum int
	Text    string
	Level   int
}

func (j *Job) resortEntriesByPage(ctx context.Context) error {
	entries, err := common.RefreshLinkedEntries(ctx, j.Book, j.TocDocID)
	if err != nil {
		return fmt.Errorf("failed to load entries: %w", err)
	}

	if len(entries) == 0 {
		return nil
	}

	sort.Slice(entries, func(i, k int) bool {
		if entries[i].ActualPage == nil && entries[k].ActualPage == nil {
			return entries[i].SortOrder < entries[k].SortOrder
		}
		if entries[i].ActualPage == nil {
			return false
		}
		if entries[k].ActualPage == nil {
			return true
		}
		return *entries[i].ActualPage < *entries[k].ActualPage
	})

	var ops []defra.WriteOp
	for i, entry := range entries {
		newSortOrder := (i + 1) * 100
		if entry.SortOrder != newSortOrder {
			ops = append(ops, defra.WriteOp{
				Collection: "TocEntry",
				DocID:      entry.DocID,
				Document: map[string]any{
					"sort_order": newSortOrder,
				},
				Op: defra.OpUpdate,
			})
		}
	}

	if len(ops) > 0 {
		if _, err := common.SendManyTracked(ctx, j.Book, ops); err != nil {
			return fmt.Errorf("failed to batch re-sort ToC entries: %w", err)
		}
	}

	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Debug("re-sorted ToC entries by page",
			"toc_doc_id", j.TocDocID,
			"entry_count", len(entries),
			"updated", len(ops))
	}

	return nil
}

// --- Finalize Agent State Cleanup ---

func (j *Job) retryFinalizeDiscoverUnit(ctx context.Context, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	var entry *common.EntryToFind
	for _, e := range j.Book.GetEntriesToFind() {
		if e.Key == info.FinalizeKey {
			entry = e
			break
		}
	}
	if entry == nil {
		return nil, nil
	}

	delete(j.FinalizeDiscoverAgents, info.FinalizeKey)

	unit := j.createChapterFinderWorkUnit(ctx, entry)
	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizeDiscover,
			FinalizePhase: FinalizePhaseDiscover,
			FinalizeKey:   info.FinalizeKey,
			RetryCount:    info.RetryCount + 1,
		})
		return []jobs.WorkUnit{*unit}, nil
	}

	return nil, nil
}

func (j *Job) retryFinalizeGapUnit(ctx context.Context, info WorkUnitInfo) ([]jobs.WorkUnit, error) {
	var gap *common.FinalizeGap
	for _, g := range j.Book.GetFinalizeGaps() {
		if g.Key == info.FinalizeKey {
			gap = g
			break
		}
	}
	if gap == nil {
		return nil, nil
	}

	delete(j.FinalizeGapAgents, info.FinalizeKey)

	unit := j.createGapInvestigatorWorkUnit(ctx, gap)
	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:      WorkUnitTypeFinalizeGap,
			FinalizePhase: FinalizePhaseValidate,
			FinalizeKey:   info.FinalizeKey,
			RetryCount:    info.RetryCount + 1,
		})
		return []jobs.WorkUnit{*unit}, nil
	}

	return nil, nil
}

// cleanupFinalizeDiscoverAgentState removes chapter finder agent state after completion.
// Uses async delete to avoid blocking the critical path.
func (j *Job) cleanupFinalizeDiscoverAgentState(ctx context.Context, entryKey string) {
	existing := j.Book.GetAgentState(common.AgentTypeChapterFinder, entryKey)
	if existing != nil && existing.AgentID != "" {
		// Async delete - fire and forget to avoid blocking critical path.
		common.DeleteAgentStateByAgentIDAsync(ctx, existing.AgentID)
	}
	j.Book.RemoveAgentState(common.AgentTypeChapterFinder, entryKey)
}

// cleanupFinalizeGapAgentState removes gap investigator agent state after completion.
// Uses async delete to avoid blocking the critical path.
func (j *Job) cleanupFinalizeGapAgentState(ctx context.Context, gapKey string) {
	existing := j.Book.GetAgentState(common.AgentTypeGapInvestigator, gapKey)
	if existing != nil && existing.AgentID != "" {
		// Async delete - fire and forget to avoid blocking critical path.
		common.DeleteAgentStateByAgentIDAsync(ctx, existing.AgentID)
	}
	j.Book.RemoveAgentState(common.AgentTypeGapInvestigator, gapKey)
}
