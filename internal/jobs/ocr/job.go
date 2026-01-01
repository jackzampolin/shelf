package ocr

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// Ensure Job implements the jobs.Job interface.
var _ jobs.Job = (*Job)(nil)

// ID returns the DefraDB record ID for this job.
func (j *Job) ID() string {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.RecordID
}

// SetRecordID sets the DefraDB record ID after the job is persisted.
func (j *Job) SetRecordID(id string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.RecordID = id
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return JobType
}

// Start initializes the job and returns the initial work units.
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Check basic preconditions (book exists, PDFs available)
	if err := j.CheckPreconditions(ctx); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return nil, fmt.Errorf("defra sink not in context")
	}

	if logger != nil {
		logger.Info("ocr.Start: loading page state",
			"book_id", j.BookID,
			"total_pages", j.TotalPages,
			"providers", j.OcrProviders)
	}

	// Load existing page state from DefraDB
	if err := j.LoadPageState(ctx); err != nil {
		return nil, fmt.Errorf("failed to load page state: %w", err)
	}

	if logger != nil {
		logger.Info("ocr.Start: loaded existing state", "existing_pages", len(j.PageState))
	}

	// Create page records for pages that don't exist yet
	var newPageNums []int
	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		if j.PageState[pageNum] == nil {
			newPageNums = append(newPageNums, pageNum)
		}
	}

	if len(newPageNums) > 0 {
		if logger != nil {
			logger.Info("ocr.Start: creating page records", "count", len(newPageNums))
		}

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

		results, err := sink.SendManySync(ctx, ops)
		if err != nil {
			return nil, fmt.Errorf("failed to create page records: %w", err)
		}

		for i, pageNum := range newPageNums {
			state := NewPageState()
			state.PageDocID = results[i].DocID
			j.PageState[pageNum] = state
		}
	}

	// Calculate expected work units
	j.TotalExpected = j.TotalPages * len(j.OcrProviders)

	// Count already completed
	for _, state := range j.PageState {
		for _, provider := range j.OcrProviders {
			if state.OcrDone[provider] {
				j.TotalCompleted++
			}
		}
	}

	if logger != nil {
		logger.Info("ocr.Start: generating work units",
			"total_expected", j.TotalExpected,
			"already_completed", j.TotalCompleted)
	}

	// Generate work units for all pages (extract + OCR)
	units := j.GenerateAllWorkUnits()

	if logger != nil {
		logger.Info("ocr.Start: work units generated", "count", len(units))
	}

	// If no work units needed, we're already done
	if len(units) == 0 {
		j.IsDone = true
	}

	return units, nil
}

// OnComplete is called when a work unit finishes.
func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Get work unit info
	info, ok := j.GetWorkUnit(result.WorkUnitID)
	if !ok {
		return nil, nil // Not our work unit
	}

	logger := svcctx.LoggerFrom(ctx)

	if !result.Success {
		// Handle failure with retry
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("work unit failed, retrying",
					"type", info.UnitType,
					"page_num", info.PageNum,
					"provider", info.Provider,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			retryUnit := j.CreateRetryUnit(info)
			if retryUnit != nil {
				j.RemoveWorkUnit(result.WorkUnitID)
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}

		if logger != nil {
			logger.Error("work unit failed after retries",
				"type", info.UnitType,
				"page_num", info.PageNum,
				"provider", info.Provider,
				"retry_count", info.RetryCount,
				"error", result.Error)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, fmt.Errorf("%s failed for page %d: %v",
			info.UnitType, info.PageNum, result.Error)
	}

	var newUnits []jobs.WorkUnit
	var err error

	// Handle successful completion based on work unit type
	switch info.UnitType {
	case "extract":
		newUnits, err = j.HandleExtractComplete(ctx, info, result)
	case "ocr":
		err = j.HandleOcrComplete(ctx, info, result)
	default:
		err = fmt.Errorf("unknown work unit type: %s", info.UnitType)
	}

	if err != nil {
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, err
	}

	j.RemoveWorkUnit(result.WorkUnitID)

	// Check if job is complete
	j.CheckCompletion()

	return newUnits, nil
}

// Done returns true when the job has completed.
func (j *Job) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.IsDone
}

// Status returns the current status of the job.
func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	// Count completed pages (all providers done)
	pagesComplete := 0
	for _, state := range j.PageState {
		if state.AllOcrDone(j.OcrProviders) {
			pagesComplete++
		}
	}

	return map[string]string{
		"book_id":         j.BookID,
		"total_pages":     fmt.Sprintf("%d", j.TotalPages),
		"pages_complete":  fmt.Sprintf("%d", pagesComplete),
		"providers":       fmt.Sprintf("%v", j.OcrProviders),
		"total_expected":  fmt.Sprintf("%d", j.TotalExpected),
		"total_completed": fmt.Sprintf("%d", j.TotalCompleted),
		"pending_units":   fmt.Sprintf("%d", len(j.PendingUnits)),
		"done":            fmt.Sprintf("%v", j.IsDone),
	}, nil
}

// Progress returns per-provider work unit progress.
func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()

	progress := make(map[string]jobs.ProviderProgress)

	for _, provider := range j.OcrProviders {
		completed := 0
		for _, state := range j.PageState {
			if state.OcrDone[provider] {
				completed++
			}
		}
		progress[provider] = jobs.ProviderProgress{
			TotalExpected: j.TotalPages,
			Completed:     completed,
		}
	}

	return progress
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return &jobs.WorkUnitMetrics{
		BookID: j.BookID,
		Stage:  JobType,
	}
}

// LoadPageState loads existing page state from DefraDB.
func (j *Job) LoadPageState(ctx context.Context) error {
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return fmt.Errorf("defra client not in context")
	}

	query := fmt.Sprintf(`{
		Page(filter: {book_id: {_eq: "%s"}}) {
			_docID
			page_num
			ocr_results {
				provider
				text
			}
		}
	}`, j.BookID)

	resp, err := defraClient.Execute(ctx, query, nil)
	if err != nil {
		return err
	}

	if errMsg := resp.Error(); errMsg != "" {
		return fmt.Errorf("query error: %s", errMsg)
	}

	pages, ok := resp.Data["Page"].([]any)
	if !ok {
		return nil // No pages yet
	}

	for _, p := range pages {
		page, ok := p.(map[string]any)
		if !ok {
			continue
		}

		pageNum := 0
		if pn, ok := page["page_num"].(float64); ok {
			pageNum = int(pn)
		}
		if pageNum == 0 {
			continue
		}

		state := NewPageState()

		if docID, ok := page["_docID"].(string); ok {
			state.PageDocID = docID
		}

		// Load OCR results
		if ocrResults, ok := page["ocr_results"].([]any); ok {
			for _, r := range ocrResults {
				result, ok := r.(map[string]any)
				if !ok {
					continue
				}
				provider, _ := result["provider"].(string)
				text, _ := result["text"].(string)
				if provider != "" && text != "" {
					state.OcrResults[provider] = text
					state.OcrDone[provider] = true
				}
			}
		}

		j.PageState[pageNum] = state
	}

	return nil
}

// CheckCompletion checks if all OCR work is complete.
func (j *Job) CheckCompletion() {
	// Check if all pages have all providers complete
	for pageNum := 1; pageNum <= j.TotalPages; pageNum++ {
		state := j.PageState[pageNum]
		if state == nil {
			return // Missing page state
		}
		if !state.AllOcrDone(j.OcrProviders) {
			return // Page not complete
		}
	}

	j.IsDone = true
}
