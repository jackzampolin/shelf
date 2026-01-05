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

// CreateMetadataWorkUnit creates a metadata extraction work unit.
func (j *Job) CreateMetadataWorkUnit(ctx context.Context) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Load first 20 pages of blended text
	pages, err := common.LoadPagesForMetadata(ctx, j.Book.BookID, LabelThresholdForBookOps)
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

	bookText := metadata.PrepareBookText(pages, LabelThresholdForBookOps)
	if bookText == "" {
		if logger != nil {
			logger.Debug("no book text available for metadata extraction",
				"book_id", j.Book.BookID)
		}
		return nil
	}

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: "metadata",
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
	return nil
}
