package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
)

// CreateTocExtractWorkUnit creates a ToC extraction work unit.
func (j *Job) CreateTocExtractWorkUnit(ctx context.Context) *jobs.WorkUnit {
	unit, unitID := common.CreateTocExtractWorkUnit(ctx, j, j.TocDocID)
	if unit != nil {
		j.RegisterWorkUnit(unitID, WorkUnitInfo{
			UnitType: WorkUnitTypeTocExtract,
		})
	}
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

	// Reload entries into memory so link_toc can use them
	entries, err := common.LoadTocEntries(ctx, j.TocDocID)
	if err != nil {
		return fmt.Errorf("failed to reload ToC entries: %w", err)
	}
	j.Book.SetTocEntries(entries)

	// Only mark complete on success (allows retries on failure)
	j.Book.TocExtract.Complete()
	return nil
}

