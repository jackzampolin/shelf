package common_structure

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	csjob "github.com/jackzampolin/shelf/internal/jobs/common_structure/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "common-structure"

// Config configures the common structure job.
type Config struct {
	StructureProvider string
	DebugAgents       bool
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.StructureProvider == "" {
		return fmt.Errorf("structure provider is required")
	}
	return nil
}

// NewJob creates a new common structure job for the given book.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Load book info
	result, err := common.LoadBook(ctx, bookID, common.LoadBookConfig{
		HomeDir:     homeDir,
		TocProvider: cfg.StructureProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  csjob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	// Verify preconditions: finalize_toc must be complete
	if !result.Book.TocFinalize.IsComplete() {
		return nil, fmt.Errorf("ToC finalization not complete - cannot build structure")
	}

	// Load linked entries (all should have actual_page after finalize_toc)
	entries, err := common.LoadLinkedEntries(ctx, result.TocDocID)
	if err != nil {
		return nil, fmt.Errorf("failed to load finalized entries: %w", err)
	}

	if len(entries) == 0 {
		return nil, fmt.Errorf("no ToC entries found for book %s", bookID)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("creating common structure job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"structure_provider", cfg.StructureProvider,
			"entries_count", len(entries),
			"linked_count", linkedCount)
	}

	return csjob.NewFromLoadResult(result, entries), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}
