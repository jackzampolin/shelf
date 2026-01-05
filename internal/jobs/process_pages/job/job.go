package job

import (
	"context"
	"fmt"
	"log/slog"

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

func (j *Job) ID() string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.RecordID
}

func (j *Job) SetRecordID(id string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.RecordID = id
}

func (j *Job) Type() string {
	return "process-pages"
}

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Check for cancellation
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}

	// Book state is already fully loaded by common.LoadBook in the factory.
	// Start() just does business logic: crash recovery, page creation, work unit generation.

	logger := svcctx.LoggerFrom(ctx)

	// Set book status to processing
	j.PersistBookStatus(ctx, BookStatusProcessing)

	// Crash recovery: if operations were started but not done, reset to retry
	if j.Book.Metadata.IsStarted() {
		j.Book.Metadata.Fail(MaxBookOpRetries)
		j.PersistMetadataState(ctx)
	}
	if j.Book.TocFinder.IsStarted() && j.TocAgent == nil {
		j.Book.TocFinder.Fail(MaxBookOpRetries)
		j.PersistTocFinderState(ctx)
	}
	if j.Book.TocExtract.IsStarted() && j.TocAgent == nil {
		j.Book.TocExtract.Fail(MaxBookOpRetries)
		j.PersistTocExtractState(ctx)
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
		logger.Info("created page records", "count", createdCount)
	}

	// Generate work units for all pages
	var units []jobs.WorkUnit
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

	if logger != nil {
		logger.Info("job started",
			"book_id", j.Book.BookID,
			"total_pages", j.Book.TotalPages,
			"work_units", len(units))
	}

	return units, nil
}

func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

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

	if !result.Success {
		// Handle failures with retry logic
		switch info.UnitType {
		case "metadata":
			j.Book.Metadata.Fail(MaxBookOpRetries)
			j.PersistMetadataState(ctx)
		case "toc_finder":
			j.Book.TocFinder.Fail(MaxBookOpRetries)
			j.PersistTocFinderState(ctx)
		case "toc_extract":
			j.Book.TocExtract.Fail(MaxBookOpRetries)
			j.PersistTocExtractState(ctx)
		default:
			// Page-level operations (extract, ocr, blend, label) - retry if under limit
			if info.RetryCount < MaxPageOpRetries {
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

	case "blend":
		units, err := j.HandleBlendComplete(ctx, info, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}

	case "label":
		units, err := j.HandleLabelComplete(ctx, info, result)
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
		}
	}

	// Handle handler errors with retry for page-level operations
	if handlerErr != nil {
		isPageOp := info.UnitType == "extract" || info.UnitType == "ocr" ||
			info.UnitType == "blend" || info.UnitType == "label"

		if isPageOp && info.RetryCount < MaxPageOpRetries {
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
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, handlerErr
	}

	// Success - remove work unit and check completion
	j.RemoveWorkUnit(result.WorkUnitID)
	j.CheckCompletion(ctx)

	return newUnits, nil
}

// createRetryUnit creates a retry work unit for a failed page-level operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo, logger *slog.Logger) *jobs.WorkUnit {
	state := j.Book.GetPage(info.PageNum)
	if state == nil {
		return nil
	}

	newRetryCount := info.RetryCount + 1
	if logger != nil {
		logger.Info("creating retry unit",
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
	case "blend":
		unit = j.CreateBlendWorkUnit(info.PageNum, state)
	case "label":
		unit = j.CreateLabelWorkUnit(ctx, info.PageNum, state)
	}

	if unit != nil {
		// Update the registered info with new retry count
		j.PendingUnits[unit.ID] = WorkUnitInfo{
			PageNum:    info.PageNum,
			UnitType:   info.UnitType,
			Provider:   info.Provider,
			RetryCount: newRetryCount,
		}
	}

	return unit
}

func (j *Job) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.IsDone
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	extractDone, ocrDone, blendDone, labelDone := 0, 0, 0, 0
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
		if state.IsBlendDone() {
			blendDone++
		}
		if state.IsLabelDone() {
			labelDone++
		}
	})

	return map[string]string{
		"book_id":             j.Book.BookID,
		"total_pages":         fmt.Sprintf("%d", j.Book.TotalPages),
		"extract_complete":    fmt.Sprintf("%d", extractDone),
		"ocr_complete":        fmt.Sprintf("%d", ocrDone),
		"blend_complete":      fmt.Sprintf("%d", blendDone),
		"label_complete":      fmt.Sprintf("%d", labelDone),
		"metadata_started":    fmt.Sprintf("%v", j.Book.Metadata.IsStarted()),
		"metadata_complete":   fmt.Sprintf("%v", j.Book.Metadata.IsComplete()),
		"toc_finder_started":  fmt.Sprintf("%v", j.Book.TocFinder.IsStarted()),
		"toc_finder_done":     fmt.Sprintf("%v", j.Book.TocFinder.IsDone()),
		"toc_found":           fmt.Sprintf("%v", j.Book.TocFound),
		"toc_start_page":      fmt.Sprintf("%d", j.Book.TocStartPage),
		"toc_end_page":        fmt.Sprintf("%d", j.Book.TocEndPage),
		"toc_extract_started": fmt.Sprintf("%v", j.Book.TocExtract.IsStarted()),
		"toc_extract_done":    fmt.Sprintf("%v", j.Book.TocExtract.IsDone()),
		"done":                fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.ProviderProgress()
}
