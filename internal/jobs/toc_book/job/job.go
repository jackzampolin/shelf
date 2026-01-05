package job

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/agents"
	toc_finder "github.com/jackzampolin/shelf/internal/agents/toc_finder"
	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// ID, SetRecordID, Done are inherited from common.BaseJob

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	// Crash recovery: reset started-but-incomplete operations
	if j.Book.TocFinder.IsStarted() && !j.Book.TocFinder.IsComplete() && j.TocAgent == nil {
		j.Book.TocFinder.Fail(MaxRetries)
		j.PersistTocFinderState(ctx)
	}
	if j.Book.TocExtract.IsStarted() && !j.Book.TocExtract.IsComplete() {
		j.Book.TocExtract.Fail(MaxRetries)
		j.PersistTocExtractState(ctx)
	}

	// Check if already complete
	if j.Book.TocFinder.IsComplete() && (!j.Book.TocFound || j.Book.TocExtract.IsComplete()) {
		if logger != nil {
			logger.Info("toc job already complete",
				"book_id", j.Book.BookID,
				"toc_found", j.Book.TocFound)
		}
		j.IsDone = true
		return nil, nil
	}

	var units []jobs.WorkUnit

	// If ToC finder not complete, start it
	if !j.Book.TocFinder.IsComplete() && j.Book.TocFinder.CanStart() {
		unit := j.CreateTocFinderWorkUnit(ctx)
		if unit != nil {
			if err := j.Book.TocFinder.Start(); err == nil {
				j.PersistTocFinderState(ctx)
				units = append(units, *unit)
			}
		}
	}

	// If ToC finder complete and ToC found, but extract not complete, start extract
	if j.Book.TocFinder.IsComplete() && j.Book.TocFound && !j.Book.TocExtract.IsComplete() && j.Book.TocExtract.CanStart() {
		unit := j.CreateTocExtractWorkUnit(ctx)
		if unit != nil {
			if err := j.Book.TocExtract.Start(); err == nil {
				j.PersistTocExtractState(ctx)
				units = append(units, *unit)
			}
		}
	}

	if logger != nil {
		logger.Info("toc job started",
			"book_id", j.Book.BookID,
			"work_units", len(units),
			"toc_finder_complete", j.Book.TocFinder.IsComplete(),
			"toc_found", j.Book.TocFound)
	}

	// If no work to do, mark as done
	if len(units) == 0 {
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
		return nil, nil
	}

	logger := svcctx.LoggerFrom(ctx)

	if !result.Success {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("toc operation failed, retrying",
					"unit_type", info.UnitType,
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			retryUnit := j.createRetryUnit(ctx, info)
			if retryUnit != nil {
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		// Mark as failed
		switch info.UnitType {
		case WorkUnitTypeTocFinder:
			j.Book.TocFinder.Fail(MaxRetries)
			j.PersistTocFinderState(ctx)
		case WorkUnitTypeTocExtract:
			j.Book.TocExtract.Fail(MaxRetries)
			j.PersistTocExtractState(ctx)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, fmt.Errorf("toc operation failed after retries: %v", result.Error)
	}

	var newUnits []jobs.WorkUnit
	var handlerErr error

	switch info.UnitType {
	case WorkUnitTypeTocFinder:
		units, err := j.HandleTocFinderComplete(ctx, result)
		if err != nil {
			handlerErr = err
		} else {
			newUnits = append(newUnits, units...)
		}
	case WorkUnitTypeTocExtract:
		if err := j.HandleTocExtractComplete(ctx, result); err != nil {
			handlerErr = err
		}
	}

	if handlerErr != nil {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("toc handler failed, retrying",
					"unit_type", info.UnitType,
					"retry_count", info.RetryCount,
					"error", handlerErr)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			retryUnit := j.createRetryUnit(ctx, info)
			if retryUnit != nil {
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		switch info.UnitType {
		case WorkUnitTypeTocFinder:
			j.Book.TocFinder.Fail(MaxRetries)
			j.PersistTocFinderState(ctx)
		case WorkUnitTypeTocExtract:
			j.Book.TocExtract.Fail(MaxRetries)
			j.PersistTocExtractState(ctx)
		}
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, handlerErr
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	j.CheckCompletion(ctx)

	return newUnits, nil
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	return map[string]string{
		"book_id":              j.Book.BookID,
		"toc_finder_started":   fmt.Sprintf("%v", j.Book.TocFinder.IsStarted()),
		"toc_finder_complete":  fmt.Sprintf("%v", j.Book.TocFinder.IsComplete()),
		"toc_found":            fmt.Sprintf("%v", j.Book.TocFound),
		"toc_extract_started":  fmt.Sprintf("%v", j.Book.TocExtract.IsStarted()),
		"toc_extract_complete": fmt.Sprintf("%v", j.Book.TocExtract.IsComplete()),
		"done":                 fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Progress: finder (1) + extract (1 if ToC found)
	total := 1
	completed := 0
	if j.Book.TocFinder.IsComplete() {
		completed++
		if j.Book.TocFound {
			total = 2
			if j.Book.TocExtract.IsComplete() {
				completed++
			}
		}
	}

	return map[string]jobs.ProviderProgress{
		j.Book.TocProvider: {
			TotalExpected: total,
			Completed:     completed,
		},
	}
}

// CheckCompletion checks if the job is complete.
func (j *Job) CheckCompletion(ctx context.Context) {
	// Complete if: finder done AND (no ToC OR extract done)
	if j.Book.TocFinder.IsComplete() && (!j.Book.TocFound || j.Book.TocExtract.IsComplete()) {
		j.IsDone = true
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Info("toc job complete",
				"book_id", j.Book.BookID,
				"toc_found", j.Book.TocFound)
		}
	}
}

// CreateTocFinderWorkUnit creates a ToC finder agent work unit.
func (j *Job) CreateTocFinderWorkUnit(ctx context.Context) *jobs.WorkUnit {
	sink := svcctx.DefraSinkFrom(ctx)
	if sink == nil {
		return nil
	}
	defraClient := svcctx.DefraClientFrom(ctx)
	if defraClient == nil {
		return nil
	}

	// Create or get ToC record
	if j.TocDocID == "" {
		// First, check if Book already has a ToC linked
		query := fmt.Sprintf(`{
			Book(filter: {_docID: {_eq: "%s"}}) {
				toc {
					_docID
				}
			}
		}`, j.Book.BookID)
		resp, err := defraClient.Execute(ctx, query, nil)
		if err == nil {
			if books, ok := resp.Data["Book"].([]any); ok && len(books) > 0 {
				if book, ok := books[0].(map[string]any); ok {
					if toc, ok := book["toc"].(map[string]any); ok {
						if docID, ok := toc["_docID"].(string); ok && docID != "" {
							j.TocDocID = docID
						}
					}
				}
			}
		}

		// Only create if no ToC exists
		if j.TocDocID == "" {
			result, err := sink.SendSync(ctx, defra.WriteOp{
				Collection: "ToC",
				Document: map[string]any{
					"toc_found":        false,
					"finder_complete":  false,
					"extract_complete": false,
					"link_complete":    false,
					"finder_started":   true,
					"created_at":       time.Now().Format(time.RFC3339Nano),
				},
				Op: defra.OpCreate,
			})
			if err != nil {
				return nil
			}
			j.TocDocID = result.DocID

			// Update the Book to link to this ToC
			_, err = sink.SendSync(ctx, defra.WriteOp{
				Collection: "Book",
				DocID:      j.Book.BookID,
				Document: map[string]any{
					"toc_id": j.TocDocID,
				},
				Op: defra.OpUpdate,
			})
			if err != nil {
				logger := svcctx.LoggerFrom(ctx)
				if logger != nil {
					logger.Warn("failed to link ToC to Book", "error", err, "toc_doc_id", j.TocDocID)
				}
			}
		}
	}

	// Create agent via factory
	j.TocAgent = agents.NewTocFinderAgent(ctx, agents.TocFinderConfig{
		BookID:       j.Book.BookID,
		TotalPages:   j.Book.TotalPages,
		DefraClient:  defraClient,
		HomeDir:      j.Book.HomeDir,
		SystemPrompt: j.GetPrompt(toc_finder.PromptKey),
		Debug:        j.Book.DebugAgents,
		JobID:        j.RecordID,
	})

	// Get first work unit using helper
	agentUnits := agents.ExecuteToolLoop(ctx, j.TocAgent)
	if len(agentUnits) == 0 {
		return nil
	}

	// Convert and return first work unit
	jobUnits := j.convertTocAgentUnits(agentUnits)
	if len(jobUnits) == 0 {
		return nil
	}
	return &jobUnits[0]
}

// HandleTocFinderComplete processes ToC finder agent work unit completion.
func (j *Job) HandleTocFinderComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
	if j.TocAgent == nil {
		return nil, fmt.Errorf("toc agent not initialized")
	}

	// Handle LLM result
	if result.ChatResult != nil {
		j.TocAgent.HandleLLMResult(result.ChatResult)

		// Execute tool loop using helper
		agentUnits := agents.ExecuteToolLoop(ctx, j.TocAgent)
		if len(agentUnits) > 0 {
			// It's an LLM call, return as work unit
			return j.convertTocAgentUnits(agentUnits), nil
		}
	}

	// Check if agent is done
	if j.TocAgent.IsDone() {
		// Save agent log if debug enabled
		if err := j.TocAgent.SaveLog(ctx); err != nil {
			logger := svcctx.LoggerFrom(ctx)
			if logger != nil {
				logger.Warn("failed to save agent log", "error", err)
			}
		}

		j.Book.TocFinder.Complete()
		j.PersistTocFinderState(ctx)
		agentResult := j.TocAgent.Result()

		if agentResult != nil && agentResult.Success {
			// Save result to DefraDB
			if tocResult, ok := agentResult.ToolResult.(*toc_finder.Result); ok {
				if err := common.SaveTocFinderResult(ctx, j.TocDocID, tocResult); err != nil {
					return nil, fmt.Errorf("failed to save ToC finder result: %w", err)
				}
				// Update in-memory state
				if tocResult.ToCPageRange != nil {
					j.Book.SetTocResult(tocResult.ToCFound, tocResult.ToCPageRange.StartPage, tocResult.ToCPageRange.EndPage)
				} else {
					j.Book.SetTocFound(tocResult.ToCFound)
				}
			}
		} else {
			// Agent failed or no ToC found
			j.Book.SetTocFound(false)
			if err := common.SaveTocFinderNoResult(ctx, j.TocDocID); err != nil {
				return nil, err
			}
		}

		// If ToC found, start extract
		if j.Book.TocFound && j.Book.TocExtract.CanStart() {
			unit := j.CreateTocExtractWorkUnit(ctx)
			if unit != nil {
				if err := j.Book.TocExtract.Start(); err == nil {
					j.PersistTocExtractState(ctx)
					return []jobs.WorkUnit{*unit}, nil
				}
			}
		}

		return nil, nil
	}

	// Agent not done but no LLM work units - shouldn't happen
	return nil, nil
}

// CreateTocExtractWorkUnit creates a ToC extraction work unit.
func (j *Job) CreateTocExtractWorkUnit(ctx context.Context) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Get ToC page range
	tocStartPage, tocEndPage := j.Book.GetTocPageRange()

	// Load ToC pages
	tocPages, err := common.LoadTocPages(ctx, j.Book.BookID, tocStartPage, tocEndPage)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to load ToC pages", "error", err)
		}
		return nil
	}
	if len(tocPages) == 0 {
		if logger != nil {
			logger.Warn("no ToC pages found",
				"start_page", tocStartPage,
				"end_page", tocEndPage)
		}
		return nil
	}

	// Load structure summary from finder (if available)
	structureSummary, _ := common.LoadTocStructureSummary(ctx, j.TocDocID)

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: WorkUnitTypeTocExtract,
	})

	unit := extract_toc.CreateWorkUnit(extract_toc.Input{
		ToCPages:             tocPages,
		StructureSummary:     structureSummary,
		SystemPromptOverride: j.GetPrompt(extract_toc.PromptKey),
	})
	unit.ID = unitID
	unit.Provider = j.Book.TocProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = "toc_extract"
	metrics.PromptKey = extract_toc.PromptKey
	metrics.PromptCID = j.GetPromptCID(extract_toc.PromptKey)
	unit.Metrics = metrics

	return unit
}

// HandleTocExtractComplete processes ToC extraction completion.
func (j *Job) HandleTocExtractComplete(ctx context.Context, result jobs.WorkResult) error {
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return fmt.Errorf("ToC extraction returned no result")
	}

	extractResult, err := extract_toc.ParseResult(result.ChatResult.ParsedJSON)
	if err != nil {
		return fmt.Errorf("failed to parse ToC extract result: %w", err)
	}

	if err := common.SaveTocExtractResult(ctx, j.TocDocID, extractResult); err != nil {
		return fmt.Errorf("failed to save ToC extract result: %w", err)
	}

	j.Book.TocExtract.Complete()
	j.PersistTocExtractState(ctx)
	return nil
}

// convertTocAgentUnits converts agent work units to job work units.
func (j *Job) convertTocAgentUnits(agentUnits []agent.WorkUnit) []jobs.WorkUnit {
	jobUnits := agents.ConvertToJobUnits(agentUnits, agents.ConvertConfig{
		JobID:     j.RecordID,
		Provider:  j.Book.TocProvider,
		Stage:     j.Type(),
		ItemKey:   "toc_finder",
		PromptKey: toc_finder.PromptKey,
		PromptCID: j.GetPromptCID(toc_finder.PromptKey),
		BookID:    j.Book.BookID,
	})

	// Register work units
	for _, u := range jobUnits {
		j.RegisterWorkUnit(u.ID, WorkUnitInfo{UnitType: WorkUnitTypeTocFinder})
	}

	return jobUnits
}

// PersistTocFinderState persists ToC finder state to DefraDB.
func (j *Job) PersistTocFinderState(ctx context.Context) {
	if err := common.PersistTocFinderState(ctx, j.TocDocID, &j.Book.TocFinder); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist toc finder state",
				"toc_doc_id", j.TocDocID,
				"error", err)
		}
	}
}

// PersistTocExtractState persists ToC extract state to DefraDB.
func (j *Job) PersistTocExtractState(ctx context.Context) {
	if err := common.PersistTocExtractState(ctx, j.TocDocID, &j.Book.TocExtract); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist toc extract state",
				"toc_doc_id", j.TocDocID,
				"error", err)
		}
	}
}

// createRetryUnit creates a retry work unit for a failed operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo) *jobs.WorkUnit {
	var unit *jobs.WorkUnit
	switch info.UnitType {
	case WorkUnitTypeTocFinder:
		// Can't retry mid-agent, need to restart
		unit = j.CreateTocFinderWorkUnit(ctx)
	case WorkUnitTypeTocExtract:
		unit = j.CreateTocExtractWorkUnit(ctx)
	}

	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   info.UnitType,
			RetryCount: info.RetryCount + 1,
		})
	}
	return unit
}
