package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
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

	// Get sink for writes
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return nil, fmt.Errorf("defra sink not in context")
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("job.Start: loading page state", "book_id", j.BookID, "total_pages", j.TotalPages)
	}

	// Load existing page state from DefraDB
	if err := j.LoadPageState(ctx); err != nil {
		return nil, fmt.Errorf("failed to load page state: %w", err)
	}

	if logger != nil {
		logger.Info("job.Start: loaded page state", "existing_pages", len(j.PageState))
	}

	// Load book-level state
	if err := j.LoadBookState(ctx); err != nil {
		return nil, fmt.Errorf("failed to load book state: %w", err)
	}

	if logger != nil {
		logger.Info("job.Start: loaded book state")
	}

	// Recover from crash during ToC operations
	// If ToC finder was started but not done and agent is nil, reset to retry
	if j.BookState.TocFinder.IsStarted() && j.TocAgent == nil {
		j.BookState.TocFinder.Fail(MaxBookOpRetries)
		j.PersistTocFinderState(ctx)
	}

	// Same for ToC extract
	if j.BookState.TocExtract.IsStarted() && j.TocAgent == nil {
		j.BookState.TocExtract.Fail(MaxBookOpRetries)
		j.PersistTocExtractState(ctx)
	}

	// First pass: identify pages that need creation
	var newPageNums []int
	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		if j.PageState[pageNum] == nil {
			newPageNums = append(newPageNums, pageNum)
		}
	}

	// Batch create all new pages
	if len(newPageNums) > 0 {
		if logger != nil {
			logger.Info("job.Start: creating page records", "pages_to_create", len(newPageNums))
		}

		// Check for cancellation before batch operation
		if err := checkCancelled(ctx); err != nil {
			return nil, err
		}

		// Build batch of create operations
		ops := make([]defra.WriteOp, len(newPageNums))
		for i, pageNum := range newPageNums {
			ops[i] = defra.WriteOp{
				Collection: "Page",
				Document: map[string]any{
					"book_id":          j.BookID,
					"page_num":         pageNum,
					"extract_complete": false,
					"ocr_complete":     false,
					"blend_complete":   false,
					"label_complete":   false,
				},
				Op: defra.OpCreate,
			}
		}

		// Send all creates at once - sink will batch them efficiently
		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			return nil, fmt.Errorf("failed to batch create page records: %w", err)
		}

		// Assign DocIDs to PageState
		for i, pageNum := range newPageNums {
			state := NewPageState()
			state.PageDocID = results[i].DocID
			j.PageState[pageNum] = state
		}

		if logger != nil {
			logger.Info("job.Start: batch page creation complete", "created", len(newPageNums))
		}
	}

	// Second pass: generate work units for all pages
	var units []jobs.WorkUnit
	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		// Check for cancellation periodically
		if pageNum%100 == 0 {
			if err := checkCancelled(ctx); err != nil {
				return nil, err
			}
		}

		state := j.PageState[pageNum]
		if state == nil {
			// Should not happen after batch create, but be safe
			continue
		}

		// Generate work units based on current state
		if !state.ExtractDone {
			// Page needs extraction first
			if unit := j.CreateExtractWorkUnit(pageNum); unit != nil {
				units = append(units, *unit)
			}
		} else {
			// Page is extracted, check what other work is needed
			newUnits := j.GeneratePageWorkUnits(ctx, pageNum, state)
			units = append(units, newUnits...)
		}
	}

	if logger != nil {
		logger.Info("job.Start: work unit generation complete", "work_units", len(units))
	}

	// Check if we should start book-level operations
	bookUnits := j.MaybeStartBookOperations(ctx)
	units = append(units, bookUnits...)

	return units, nil
}

func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Check for cancellation
	if err := checkCancelled(ctx); err != nil {
		return nil, err
	}

	info, ok := j.GetAndRemoveWorkUnit(result.WorkUnitID)
	if !ok {
		return nil, nil // Not our work unit
	}

	if !result.Success {
		// Handle book-level operation failures with retry logic
		switch info.UnitType {
		case "metadata":
			j.BookState.Metadata.Fail(MaxBookOpRetries)
			j.PersistMetadataState(ctx) // Persist to DefraDB
		case "toc_finder":
			j.BookState.TocFinder.Fail(MaxBookOpRetries)
			j.PersistTocFinderState(ctx) // Persist to DefraDB
		case "toc_extract":
			j.BookState.TocExtract.Fail(MaxBookOpRetries)
			j.PersistTocExtractState(ctx) // Persist to DefraDB
		}
		return nil, fmt.Errorf("work unit failed (%s): %v", info.UnitType, result.Error)
	}

	var newUnits []jobs.WorkUnit

	switch info.UnitType {
	case "extract":
		units, err := j.HandleExtractComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "ocr":
		units, err := j.HandleOcrComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "blend":
		units, err := j.HandleBlendComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "label":
		units, err := j.HandleLabelComplete(ctx, info, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "metadata":
		if err := j.HandleMetadataComplete(ctx, result); err != nil {
			return nil, err
		}

	case "toc_finder":
		units, err := j.HandleTocFinderComplete(ctx, result)
		if err != nil {
			return nil, err
		}
		newUnits = append(newUnits, units...)

	case "toc_extract":
		if err := j.HandleTocExtractComplete(ctx, result); err != nil {
			return nil, err
		}
	}

	// Check overall completion
	j.CheckCompletion()

	return newUnits, nil
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
	for _, state := range j.PageState {
		if state.ExtractDone {
			extractDone++
		}
		allOcr := true
		for _, provider := range j.OcrProviders {
			if !state.OcrDone[provider] {
				allOcr = false
				break
			}
		}
		if allOcr {
			ocrDone++
		}
		if state.BlendDone {
			blendDone++
		}
		if state.LabelDone {
			labelDone++
		}
	}

	return map[string]string{
		"book_id":             j.BookID,
		"total_pages":         fmt.Sprintf("%d", j.TotalPages),
		"extract_complete":    fmt.Sprintf("%d", extractDone),
		"ocr_complete":        fmt.Sprintf("%d", ocrDone),
		"blend_complete":      fmt.Sprintf("%d", blendDone),
		"label_complete":      fmt.Sprintf("%d", labelDone),
		"metadata_started":    fmt.Sprintf("%v", j.BookState.Metadata.IsStarted()),
		"metadata_complete":   fmt.Sprintf("%v", j.BookState.Metadata.IsComplete()),
		"toc_finder_started":  fmt.Sprintf("%v", j.BookState.TocFinder.IsStarted()),
		"toc_finder_done":     fmt.Sprintf("%v", j.BookState.TocFinder.IsDone()),
		"toc_found":           fmt.Sprintf("%v", j.BookState.TocFound),
		"toc_start_page":      fmt.Sprintf("%d", j.BookState.TocStartPage),
		"toc_end_page":        fmt.Sprintf("%d", j.BookState.TocEndPage),
		"toc_extract_started": fmt.Sprintf("%v", j.BookState.TocExtract.IsStarted()),
		"toc_extract_done":    fmt.Sprintf("%v", j.BookState.TocExtract.IsDone()),
		"done":                fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.ProviderProgress()
}
