package job

import (
	"context"
	"fmt"
	"log/slog"

	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// checkCancelled returns an error if the context is cancelled.
func checkCancelled(ctx context.Context) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
		return nil
	}
}

// ID, SetRecordID, Done are inherited from common.BaseJob

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Check for cancellation
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}

	// Book state is already fully loaded by common.LoadBook in the factory.
	// Start() just does business logic: crash recovery, page creation, work unit generation.

	logger := svcctx.LoggerFrom(ctx)
	var resumeUnits []jobs.WorkUnit

	// Set book status to processing
	j.PersistBookStatus(ctx, BookStatusProcessing)

	// Crash recovery: if operations were started but not done, check if we can resume
	// via saved agent state. If no saved state, fail/retry the operation.
	if j.Book.MetadataIsStarted() {
		j.Book.MetadataFail(MaxBookOpRetries)
		j.PersistMetadataState(ctx)
	}
	// ToC finder: check for saved agent state before failing
	if j.Book.TocFinderIsStarted() && j.TocAgent == nil {
		savedState := j.Book.GetAgentState(AgentTypeTocFinder, "")
		if savedState == nil || savedState.Complete {
			// No saved state or agent already completed - fail/retry
			j.Book.TocFinderFail(MaxBookOpRetries)
			j.PersistTocFinderState(ctx)
		} else if unit := j.CreateTocFinderWorkUnit(ctx); unit != nil {
			resumeUnits = append(resumeUnits, *unit)
		} else {
			// A resumable agent state existed, but it could not emit work. Reset
			// through the normal retry path so MaybeStartBookOperations can try
			// a fresh ToC finder below instead of leaving the job stuck started.
			j.Book.TocFinderFail(MaxBookOpRetries)
			j.PersistTocFinderState(ctx)
		}
	}
	if j.Book.TocExtractIsStarted() && j.TocAgent == nil {
		j.Book.TocExtractFail(MaxBookOpRetries)
		j.PersistTocExtractState(ctx)
	}
	j.reconcileTocLinkRecovery(ctx)
	// TocFinalize: fail/retry if started but not done. Pattern analysis results
	// are preserved in pattern_analysis_json and will be reused on retry.
	if j.Book.TocFinalizeIsStarted() {
		j.Book.TocFinalizeFail(MaxBookOpRetries)
		// Persist async - memory is authoritative during execution
		common.PersistOpStateAsync(ctx, j.Book, common.OpTocFinalize)
	}
	// Structure: fail/retry if started but not done.
	if j.Book.StructureIsStarted() {
		j.Book.StructureFail(MaxBookOpRetries)
		// Persist async - memory is authoritative during execution
		common.PersistOpStateAsync(ctx, j.Book, common.OpStructure)
	}

	// Create any missing page records in DB
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}
	createdCount, err := common.CreateMissingPages(ctx, j.Book)
	if err != nil {
		return nil, fmt.Errorf("failed to create page records: %w", err)
	}
	if createdCount > 0 && logger != nil {
		logger.Debug("created page records", "count", createdCount)
	}

	// Generate work units for all pages
	units := resumeUnits
	for pageNum := 1; pageNum <= j.Book.TotalPages; pageNum++ {
		if pageNum%100 == 0 {
			if err := checkCancelled(ctx); err != nil {
				return nil, err
			}
		}

		state := j.Book.GetPage(pageNum)
		if state == nil {
			continue
		}

		if !state.IsExtractDone() {
			if unit := j.CreateExtractWorkUnit(pageNum); unit != nil {
				units = append(units, *unit)
			}
		} else {
			newUnits := j.GeneratePageWorkUnits(ctx, pageNum, state)
			units = append(units, newUnits...)
		}
	}

	// Add book-level operations if ready
	bookUnits := j.MaybeStartBookOperations(ctx)
	units = append(units, bookUnits...)

	j.CheckCompletion(ctx)

	if logger != nil {
		logger.Debug("process_book job started",
			"book_id", j.Book.BookID,
			"total_pages", j.Book.TotalPages,
			"work_units", len(units))
	}

	return units, nil
}

// reconcileTocLinkRecovery repairs ToC link operation state after restart.
//
// LoadBook only loads ToC entries that still lack an actual_page link. If the
// process died after linking some entries, the persisted progress counters can
// describe the old full work set rather than the current pending set. Treat the
// database links as authoritative: pending entries should be attempted again,
// while an in-progress/failed link op with no pending entries is complete.
func (j *Job) reconcileTocLinkRecovery(ctx context.Context) {
	if !j.Book.EnableTocLink || !j.Book.TocExtractIsDone() {
		return
	}

	pendingEntries := j.Book.GetTocEntries()
	j.cleanupLinkedTocAgentStates(ctx, pendingEntries)
	state := j.Book.GetTocLinkState()
	if !state.IsStarted() && !state.IsFailed() && !(state.IsComplete() && len(pendingEntries) > 0) {
		return
	}
	logger := svcctx.LoggerFrom(ctx)

	if len(pendingEntries) == 0 {
		j.Book.SetTocLinkProgress(0, 0)
		common.PersistTocLinkProgressAsync(ctx, j.Book)
		j.Book.SetOpState(common.OpTocLink, false, true, false, 0)
		j.Book.PersistOpStateAsync(ctx, common.OpTocLink)
		if logger != nil {
			logger.Info("reconciled ToC link state as complete",
				"book_id", j.Book.BookID,
				"reason", "no_pending_entries")
		}
		return
	}

	oldTotal, oldDone := j.Book.GetTocLinkProgress()
	j.Book.SetTocLinkProgress(len(pendingEntries), 0)
	common.PersistTocLinkProgressAsync(ctx, j.Book)
	j.Book.SetOpState(common.OpTocLink, false, false, false, 0)
	j.Book.PersistOpStateAsync(ctx, common.OpTocLink)
	if logger != nil {
		logger.Info("reconciled ToC link state for pending entries",
			"book_id", j.Book.BookID,
			"pending_entries", len(pendingEntries),
			"old_total", oldTotal,
			"old_done", oldDone,
			"was_started", state.IsStarted(),
			"was_failed", state.IsFailed())
	}
}

func (j *Job) cleanupLinkedTocAgentStates(ctx context.Context, pendingEntries []*toc_entry_finder.TocEntry) {
	pending := make(map[string]struct{}, len(pendingEntries))
	for _, entry := range pendingEntries {
		pending[entry.DocID] = struct{}{}
	}

	logger := svcctx.LoggerFrom(ctx)
	deleted := 0
	for _, state := range j.Book.GetAllAgentStates() {
		if state.AgentType != common.AgentTypeTocEntryFinder {
			continue
		}
		if _, stillPending := pending[state.EntryDocID]; stillPending {
			continue
		}
		if err := j.Book.DeleteAgentStateByKeys(ctx, state.AgentType, state.EntryDocID); err != nil {
			if logger != nil {
				logger.Warn("failed to delete stale linked ToC agent state",
					"book_id", j.Book.BookID,
					"entry_doc_id", state.EntryDocID,
					"agent_id", state.AgentID,
					"error", err)
			}
			continue
		}
		deleted++
	}
	if deleted > 0 && logger != nil {
		logger.Info("deleted stale linked ToC agent states",
			"book_id", j.Book.BookID,
			"count", deleted)
	}
}

// maybeCompleteTocLink marks the ToC link stage complete and triggers the next
// book operation (finalize) once every entry has been resolved (linked or
// skipped). Returns any work units produced by the downstream trigger.
func (j *Job) maybeCompleteTocLink(ctx context.Context) []jobs.WorkUnit {
	total, done := j.Book.GetTocLinkProgress()
	if done < total {
		return nil
	}
	j.Book.TocLinkComplete()
	if _, err := common.PersistOpComplete(ctx, j.Book, common.OpTocLink); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist toc link completion", "error", err)
		}
	}
	return j.MaybeStartBookOperations(ctx)
}

func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Check for cancellation
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}

	// Get work unit info (don't remove yet - we may need to retry)
	info, ok := j.GetWorkUnit(result.WorkUnitID)
	if !ok {
		return nil, nil // Not our work unit
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Debug("received work unit result",
			"unit_id", result.WorkUnitID,
			"unit_type", info.UnitType,
			"page_num", info.PageNum,
			"provider", info.Provider,
			"success", result.Success,
			"has_ocr_result", result.OCRResult != nil,
			"has_chat_result", result.ChatResult != nil,
			"error", result.Error)
	}

	// Write-through cache: track costs on BookState
	// Extract cost from either ChatResult or OCRResult
	var cost float64
	if result.ChatResult != nil {
		cost = result.ChatResult.CostUSD
	} else if result.OCRResult != nil {
		cost = result.OCRResult.CostUSD
	}
	if cost > 0 {
		j.Book.AddCost(info.UnitType, cost)
	}

	if !result.Success {
		// Handle failures with retry logic
		switch info.UnitType {
		case WorkUnitTypeMetadata:
			if info.RetryCount < MaxBookOpRetries && jobs.IsRetriableError(result.Error) {
				retryUnit := j.createBookOpRetryUnit(ctx, info, logger)
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			j.markBookOpRetryExhausted(common.OpMetadata)
			j.PersistMetadataState(ctx)
		case WorkUnitTypeTocFinder:
			if info.RetryCount < MaxBookOpRetries && jobs.IsRetriableError(result.Error) {
				retryUnit := j.createBookOpRetryUnit(ctx, info, logger)
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			j.markBookOpRetryExhausted(common.OpTocFinder)
			j.PersistTocFinderState(ctx)
		case WorkUnitTypeTocExtract:
			if info.RetryCount < MaxBookOpRetries && jobs.IsRetriableError(result.Error) {
				retryUnit := j.createBookOpRetryUnit(ctx, info, logger)
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			j.markBookOpRetryExhausted(common.OpTocExtract)
			j.PersistTocExtractState(ctx)
		case WorkUnitTypeLinkToc:
			// Link ToC entry failures - retry individual entry
			if info.RetryCount < MaxBookOpRetries {
				retryUnit := j.createLinkTocRetryUnit(ctx, info, linkTocWorkFailureReason(result))
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			// Retries exhausted: skip this entry rather than failing the book.
			if logger != nil {
				logger.Warn("link_toc entry failed after retries; skipping entry to keep the book processing",
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			units := j.resolveTocLinkEntry(ctx, info)
			units = append(units, j.maybeCompleteTocLink(ctx)...)
			j.CheckCompletion(ctx)
			return units, nil
		case WorkUnitTypeOCR:
			// Transient failures (timeouts, dropped connections) are common against
			// self-hosted inference. Retry first; the round-robin lands the retry on
			// a healthy endpoint.
			if info.RetryCount < maxRetriesForPageWorkUnit(info.UnitType) {
				retryUnit := j.createRetryUnit(ctx, info, logger)
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			// Retries exhausted: skip this (likely pathological) page rather than
			// failing the whole book. The page is recorded resolved with no text,
			// like a blank page, so it is not re-emitted and downstream stages run.
			j.skipFailedOcrPage(ctx, info, result.Error)
			j.RemoveWorkUnit(result.WorkUnitID)
			// Resolving the page may have satisfied a downstream threshold (e.g. the
			// last front-matter page), so trigger book operations exactly as a
			// successful OCR does; otherwise the book stalls with OCR "done" but
			// nothing downstream started.
			bookUnits := j.MaybeStartBookOperations(ctx)
			j.CheckCompletion(ctx)
			return bookUnits, nil
		case WorkUnitTypeExtract:
			// Retry first; transient extract failures recover.
			if info.RetryCount < maxRetriesForPageWorkUnit(info.UnitType) {
				retryUnit := j.createRetryUnit(ctx, info, logger)
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			// Retries exhausted: the page image can't be produced (corrupt/
			// pathological page), so the page can't be OCR'd. Skip it rather than
			// failing the whole book, then trigger downstream just like a resolved
			// page would.
			j.skipFailedExtractPage(ctx, info, result.Error)
			j.RemoveWorkUnit(result.WorkUnitID)
			bookUnits := j.MaybeStartBookOperations(ctx)
			j.CheckCompletion(ctx)
			return bookUnits, nil
		default:
			// Any other work type - retry if under limit, else fall through to fatal.
			if info.RetryCount < maxRetriesForPageWorkUnit(info.UnitType) {
				retryUnit := j.createRetryUnit(ctx, info, logger)
				if retryUnit != nil {
					j.RemoveWorkUnit(result.WorkUnitID)
					return []jobs.WorkUnit{*retryUnit}, nil
				}
			}
			if logger != nil {
				logger.Error("page operation failed after retries",
					"unit_type", info.UnitType,
					"page_num", info.PageNum,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, fmt.Errorf("work unit failed (%s): %v", info.UnitType, result.Error)
	}

	var newUnits []jobs.WorkUnit
	var handlerErr error

	switch info.UnitType {
	case "extract":
		units, err := j.HandleExtractComplete(ctx, info, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case "ocr":
		units, err := j.HandleOcrComplete(ctx, info, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case "metadata":
		if err := j.HandleMetadataComplete(ctx, result); err != nil {
			handlerErr = err
		}

	case "toc_finder":
		units, err := j.HandleTocFinderComplete(ctx, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case "toc_extract":
		if err := j.HandleTocExtractComplete(ctx, result); err != nil {
			handlerErr = err
		} else {
			// ToC extraction complete - check if we should start linking
			newUnits = append(newUnits, j.MaybeStartBookOperations(ctx)...)
		}

	case WorkUnitTypeLinkToc:
		units, err := j.HandleLinkTocComplete(ctx, result, info)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
			// Complete the link stage and trigger finalize once every entry is
			// resolved (linked or skipped).
			newUnits = append(newUnits, j.maybeCompleteTocLink(ctx)...)
		}

	case WorkUnitTypeFinalizePattern, WorkUnitTypeFinalizeDiscover, WorkUnitTypeFinalizeGap:
		units, err := j.HandleFinalizeComplete(ctx, result, info)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case WorkUnitTypeStructureClassify, WorkUnitTypeStructurePolish:
		units, err := j.HandleStructureComplete(ctx, result, info)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}
	}

	// Handle handler errors with retry for page-level operations and
	// per-entry ToC linking. Link retries need a fresh agent because the
	// existing one may have completed with unusable state.
	if handlerErr != nil {
		isPageOp := info.UnitType == "extract" || info.UnitType == "ocr"

		if isRetriableBookOpHandlerError(info.UnitType) && info.RetryCount < MaxBookOpRetries {
			if logger != nil {
				logger.Warn("book operation handler failed, retrying",
					"unit_type", info.UnitType,
					"retry_count", info.RetryCount,
					"error", handlerErr)
			}
			retryUnit := j.createBookOpRetryUnit(ctx, info, logger)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}

		if isPageOp && info.RetryCount < maxRetriesForPageWorkUnit(info.UnitType) {
			if logger != nil {
				logger.Warn("handler failed, retrying",
					"unit_type", info.UnitType,
					"page_num", info.PageNum,
					"retry_count", info.RetryCount,
					"error", handlerErr)
			}
			retryUnit := j.createRetryUnit(ctx, info, logger)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		if info.UnitType == WorkUnitTypeLinkToc && info.RetryCount < MaxBookOpRetries {
			if logger != nil {
				logger.Warn("link_toc handler failed, retrying entry",
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"error", handlerErr)
			}
			retryUnit := j.createLinkTocRetryUnit(ctx, info, handlerErr)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		if info.UnitType == WorkUnitTypeLinkToc {
			// Retries exhausted (or retry creation failed): skip this entry rather
			// than failing the book.
			if logger != nil {
				logger.Warn("link_toc handler failed after retries; skipping entry to keep the book processing",
					"entry_doc_id", info.EntryDocID,
					"retry_count", info.RetryCount,
					"error", handlerErr)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			units := j.resolveTocLinkEntry(ctx, info)
			units = append(units, j.maybeCompleteTocLink(ctx)...)
			j.CheckCompletion(ctx)
			return units, nil
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, handlerErr
	}

	// Success - remove work unit and check completion
	j.RemoveWorkUnit(result.WorkUnitID)
	j.CheckCompletion(ctx)

	return newUnits, nil
}

func isRetriableBookOpHandlerError(unitType string) bool {
	switch unitType {
	case WorkUnitTypeMetadata, WorkUnitTypeTocExtract:
		return true
	default:
		return false
	}
}

func (j *Job) createBookOpRetryUnit(ctx context.Context, info WorkUnitInfo, logger *slog.Logger) *jobs.WorkUnit {
	newRetryCount := info.RetryCount + 1
	if logger != nil {
		logger.Warn("book operation failed, retrying",
			"unit_type", info.UnitType,
			"retry_count", newRetryCount,
			"max_retries", MaxBookOpRetries)
	}

	var unit *jobs.WorkUnit
	switch info.UnitType {
	case WorkUnitTypeMetadata:
		unit = j.CreateMetadataWorkUnit(ctx)
	case WorkUnitTypeTocFinder:
		unit = j.CreateTocFinderWorkUnit(ctx)
	case WorkUnitTypeTocExtract:
		unit = j.CreateTocExtractWorkUnit(ctx)
	}

	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   info.UnitType,
			RetryCount: newRetryCount,
		})
	}

	return unit
}

func (j *Job) markBookOpRetryExhausted(op common.OpType) {
	j.Book.SetOpState(op, false, false, true, MaxBookOpRetries)
}

// createRetryUnit creates a retry work unit for a failed page-level operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo, logger *slog.Logger) *jobs.WorkUnit {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil
	}

	newRetryCount := info.RetryCount + 1
	if logger != nil {
		logger.Debug("creating retry unit",
			"unit_type", info.UnitType,
			"page_num", info.PageNum,
			"retry_count", newRetryCount)
	}

	var unit *jobs.WorkUnit
	switch info.UnitType {
	case "extract":
		unit = j.CreateExtractWorkUnit(info.PageNum)
	case "ocr":
		unit = j.CreateOcrWorkUnit(ctx, info.PageNum, info.Provider)
	}

	if unit != nil {
		// Update the registered info with new retry count
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			PageNum:    info.PageNum,
			UnitType:   info.UnitType,
			Provider:   info.Provider,
			RetryCount: newRetryCount,
		})
	}

	return unit
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	extractDone, ocrDone := 0, 0
	j.Book.ForEachPage(func(pageNum int, state *PageState) {
		// Use thread-safe accessors for all field reads
		if state.IsExtractDone() {
			extractDone++
		}
		allOcr := true
		for _, provider := range j.Book.OcrProviders {
			if !state.OcrComplete(provider) {
				allOcr = false
				break
			}
		}
		if allOcr {
			ocrDone++
		}
	})

	// Get ToC page range using thread-safe accessor
	tocStartPage, tocEndPage := j.Book.GetTocPageRange()

	return map[string]string{
		"book_id":             j.Book.BookID,
		"total_pages":         fmt.Sprintf("%d", j.Book.TotalPages),
		"extract_complete":    fmt.Sprintf("%d", extractDone),
		"ocr_complete":        fmt.Sprintf("%d", ocrDone),
		"metadata_started":    fmt.Sprintf("%v", j.Book.MetadataIsStarted()),
		"metadata_complete":   fmt.Sprintf("%v", j.Book.MetadataIsComplete()),
		"toc_finder_started":  fmt.Sprintf("%v", j.Book.TocFinderIsStarted()),
		"toc_finder_done":     fmt.Sprintf("%v", j.Book.TocFinderIsDone()),
		"toc_found":           fmt.Sprintf("%v", j.Book.GetTocFound()),
		"toc_start_page":      fmt.Sprintf("%d", tocStartPage),
		"toc_end_page":        fmt.Sprintf("%d", tocEndPage),
		"toc_extract_started": fmt.Sprintf("%v", j.Book.TocExtractIsStarted()),
		"toc_extract_done":    fmt.Sprintf("%v", j.Book.TocExtractIsDone()),
		"toc_link_started":    fmt.Sprintf("%v", j.Book.TocLinkIsStarted()),
		"toc_link_done":       fmt.Sprintf("%v", j.Book.TocLinkIsDone()),
		"toc_link_entries":    fmt.Sprintf("%d", func() int { t, _ := j.Book.GetTocLinkProgress(); return t }()),
		"toc_link_complete":   fmt.Sprintf("%d", func() int { _, d := j.Book.GetTocLinkProgress(); return d }()),
		"done":                fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.BaseJob.ProviderProgress()
}

// FailBook marks the book terminally failed with a reason. Implements
// jobs.BookFailer; called by the scheduler when this job dies so the book does
// not stay stuck in "processing".
func (j *Job) FailBook(ctx context.Context, reason string) {
	if j.Book == nil {
		return
	}
	if _, err := j.Book.PersistBookStatusWithReason(ctx, string(BookStatusFailed), reason); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist book failed status",
				"book_id", j.Book.BookID, "error", err)
		}
	}
}
