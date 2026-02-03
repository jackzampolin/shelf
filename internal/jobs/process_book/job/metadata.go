package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/metadata"
	"github.com/jackzampolin/shelf/internal/svcctx"
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

	cid, err := common.SaveMetadataResult(ctx, j.Book.BookID, *metadataResult)
	if err != nil {
		return fmt.Errorf("failed to save metadata: %w", err)
	}
	if cid != "" {
		j.Book.SetBookCID(cid)
		j.Book.SetOperationCID(common.OpMetadata, cid)
	}
	if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "Book", j.Book.BookID, cid); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to update metric output ref", "error", err)
		}
	}

	j.Book.MetadataComplete()
	return nil
}
