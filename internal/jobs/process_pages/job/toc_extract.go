package job

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	"github.com/jackzampolin/shelf/internal/prompts/extract_toc"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// CreateTocExtractWorkUnit creates a ToC extraction work unit.
func (j *Job) CreateTocExtractWorkUnit(ctx context.Context) *jobs.WorkUnit {
	logger := svcctx.LoggerFrom(ctx)

	// Load ToC pages
	tocPages, err := common.LoadTocPages(ctx, j.Book.BookID, j.Book.TocStartPage, j.Book.TocEndPage)
	if err != nil {
		if logger != nil {
			logger.Warn("failed to load ToC pages", "error", err)
		}
		return nil
	}
	if len(tocPages) == 0 {
		if logger != nil {
			logger.Warn("no ToC pages found",
				"start_page", j.Book.TocStartPage,
				"end_page", j.Book.TocEndPage)
		}
		return nil
	}

	// Load structure summary from finder (if available)
	structureSummary, _ := common.LoadTocStructureSummary(ctx, j.TocDocID)

	unitID := uuid.New().String()
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType: "toc_extract",
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

	// Only mark complete on success (allows retries on failure)
	j.Book.TocExtract.Complete()
	return nil
}

