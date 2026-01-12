package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
)

// CreateMetadataWorkUnit creates a metadata extraction work unit.
func (j *Job) CreateMetadataWorkUnit(ctx context.Context) *jobs.WorkUnit {
	unit, unitID := common.CreateMetadataWorkUnit(ctx, j)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			UnitType: WorkUnitTypeMetadata,
		})
	}
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
