package job

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
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

	cid, err := common.SaveTocExtractResult(ctx, j.TocDocID, extractResult)
	if err != nil {
		return fmt.Errorf("failed to save ToC extract result: %w", err)
	}
	if cid != "" {
		j.Book.SetTocCID(cid)
		j.Book.SetOperationCID(common.OpTocExtract, cid)
	}
	if err := common.UpdateMetricOutputRef(ctx, result.MetricDocID, "ToC", j.TocDocID, cid); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to update metric output ref", "error", err)
		}
	}

	// Flush sink to ensure entries are written before loading
	if sink := svcctx.DefraSinkFrom(ctx); sink != nil {
		if err := sink.Flush(ctx); err != nil {
			return fmt.Errorf("failed to flush ToC entries: %w", err)
		}
	}

	// Reload entries into memory so link_toc can use them
	entries, err := common.LoadTocEntries(ctx, j.TocDocID)
	if err != nil {
		return fmt.Errorf("failed to reload ToC entries: %w", err)
	}
	if logger := svcctx.LoggerFrom(ctx); logger != nil {
		logger.Info("loaded ToC entries after extraction",
			"toc_doc_id", j.TocDocID,
			"entry_count", len(entries))
	}
	j.Book.SetTocEntries(entries)

	// Only mark complete on success (allows retries on failure)
	j.Book.TocExtractComplete()
	return nil
}
