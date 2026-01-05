package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// MaxPagesForMetadata is the number of pages to use for metadata extraction.
const MaxPagesForMetadata = 20

// ID, SetRecordID, Done are inherited from common.BaseJob

func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	if err := ctx.Err(); err != nil {
		return nil, err
	}

	logger := svcctx.LoggerFrom(ctx)

	// Check if metadata is already complete
	if j.Book.Metadata.IsComplete() {
		if logger != nil {
			logger.Info("metadata already complete",
				"book_id", j.Book.BookID)
		}
		j.IsDone = true
		return nil, nil
	}

	// Reset if previously failed/started (crash recovery)
	if j.Book.Metadata.IsStarted() && !j.Book.Metadata.IsComplete() {
		j.Book.Metadata.Fail(MaxRetries)
		j.PersistMetadataState(ctx)
	}

	// Create metadata work unit
	unit := j.CreateMetadataWorkUnit(ctx)
	if unit == nil {
		if logger != nil {
			logger.Warn("failed to create metadata work unit",
				"book_id", j.Book.BookID)
		}
		return nil, fmt.Errorf("failed to create metadata work unit")
	}

	// Mark as started
	j.Book.Metadata.Start()
	j.PersistMetadataState(ctx)

	if logger != nil {
		logger.Info("metadata job started",
			"book_id", j.Book.BookID)
	}

	return []jobs.WorkUnit{*unit}, nil
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
				logger.Warn("metadata extraction failed, retrying",
					"retry_count", info.RetryCount,
					"error", result.Error)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			retryUnit := j.createRetryUnit(ctx, info)
			if retryUnit != nil {
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		j.Book.Metadata.Fail(MaxRetries)
		j.PersistMetadataState(ctx)
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, fmt.Errorf("metadata extraction failed after retries: %v", result.Error)
	}

	// Handle successful completion
	if err := j.HandleMetadataComplete(ctx, result); err != nil {
		if info.RetryCount < MaxRetries {
			if logger != nil {
				logger.Warn("metadata handler failed, retrying",
					"retry_count", info.RetryCount,
					"error", err)
			}
			j.RemoveWorkUnit(result.WorkUnitID)
			retryUnit := j.createRetryUnit(ctx, info)
			if retryUnit != nil {
				return []jobs.WorkUnit{*retryUnit}, nil
			}
		}
		j.Book.Metadata.Fail(MaxRetries)
		j.PersistMetadataState(ctx)
		j.RemoveWorkUnit(result.WorkUnitID)
		return nil, err
	}

	j.RemoveWorkUnit(result.WorkUnitID)
	j.IsDone = true

	if logger != nil {
		logger.Info("metadata job complete",
			"book_id", j.Book.BookID)
	}

	return nil, nil
}

func (j *Job) Status(ctx context.Context) (map[string]string, error) {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	return map[string]string{
		"book_id":           j.Book.BookID,
		"metadata_started":  fmt.Sprintf("%v", j.Book.Metadata.IsStarted()),
		"metadata_complete": fmt.Sprintf("%v", j.Book.Metadata.IsComplete()),
		"done":              fmt.Sprintf("%v", j.IsDone),
	}, nil
}

func (j *Job) Progress() map[string]jobs.ProviderProgress {
	j.Mu.Lock()
	defer j.Mu.Unlock()

	// Simple progress: 0 or 1 for metadata
	completed := 0
	if j.Book.Metadata.IsComplete() {
		completed = 1
	}

	return map[string]jobs.ProviderProgress{
		j.Book.MetadataProvider: {
			TotalExpected: 1,
			Completed:     completed,
		},
	}
}

// CreateMetadataWorkUnit creates a metadata extraction work unit.
func (j *Job) CreateMetadataWorkUnit(ctx context.Context) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Load first N pages of blended text
	pages, err := common.LoadPagesForMetadata(ctx, j.Book.BookID, MaxPagesForMetadata)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to load pages for metadata extraction",
				"book_id", j.Book.BookID,
				"error", err)
		}
		return nil
	}
	if len(pages) == 0 {
		if logger != nil {
			logger.Debug("no pages available for metadata extraction",
				"book_id", j.Book.BookID)
		}
		return nil
	}

	bookText := metadata.PrepareBookText(pages, MaxPagesForMetadata)
	if bookText == "" {
		if logger != nil {
			logger.Debug("no book text available for metadata extraction",
				"book_id", j.Book.BookID)
		}
		return nil
	}

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: WorkUnitTypeMetadata,
	})

	unit := metadata.CreateWorkUnit(metadata.Input{
		BookText:             bookText,
		SystemPromptOverride: j.GetPrompt(metadata.SystemPromptKey),
	})
	unit.ID = unitID
	unit.Provider = j.Book.MetadataProvider
	unit.JobID = j.RecordID

	metrics := j.MetricsFor()
	metrics.ItemKey = "metadata"
	metrics.PromptKey = metadata.SystemPromptKey
	metrics.PromptCID = j.GetPromptCID(metadata.SystemPromptKey)
	unit.Metrics = metrics

	return unit
}

// HandleMetadataComplete processes metadata extraction completion.
func (j *Job) HandleMetadataComplete(ctx context.Context, result jobs.WorkResult) error {
	if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
		return fmt.Errorf("metadata extraction returned no result")
	}

	metadataResult, err := metadata.ParseResult(result.ChatResult.ParsedJSON)
	if err != nil {
		return fmt.Errorf("failed to parse metadata result: %w", err)
	}

	if err := common.SaveMetadataResult(ctx, j.Book.BookID, *metadataResult); err != nil {
		return fmt.Errorf("failed to save metadata: %w", err)
	}

	j.Book.Metadata.Complete()
	j.PersistMetadataState(ctx)
	return nil
}

// PersistMetadataState saves the metadata operation state to DefraDB.
func (j *Job) PersistMetadataState(ctx context.Context) {
	if err := common.PersistMetadataState(ctx, j.Book.BookID, &j.Book.Metadata); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist metadata state",
				"book_id", j.Book.BookID,
				"error", err)
		}
	}
}

// createRetryUnit creates a retry work unit for a failed operation.
func (j *Job) createRetryUnit(ctx context.Context, info WorkUnitInfo) *jobs.WorkUnit {
	unit := j.CreateMetadataWorkUnit(ctx)
	if unit != nil {
		j.Tracker.Register(unit.ID, WorkUnitInfo{
			UnitType:   WorkUnitTypeMetadata,
			RetryCount: info.RetryCount + 1,
		})
	}
	return unit
}
