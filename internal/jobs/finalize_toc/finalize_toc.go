package finalize_toc

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	fjob "github.com/jackzampolin/shelf/internal/jobs/finalize_toc/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "finalize-toc"

// Config configures the finalize toc job.
type Config struct {
	TocProvider string
	DebugAgents bool
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.TocProvider == "" {
		return fmt.Errorf("toc provider is required")
	}
	return nil
}

// NewJob creates a new finalize toc job for the given book.
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
		TocProvider: cfg.TocProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  fjob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	// Verify preconditions: link_toc must be complete
	if !result.Book.TocLink.IsComplete() {
		return nil, fmt.Errorf("ToC linking not complete - cannot finalize")
	}

	// Load linked entries
	entries, err := common.LoadLinkedEntries(ctx, result.TocDocID)
	if err != nil {
		return nil, fmt.Errorf("failed to load linked entries: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		linkedCount := 0
		for _, e := range entries {
			if e.ActualPage != nil {
				linkedCount++
			}
		}
		logger.Info("creating finalize toc job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"toc_provider", cfg.TocProvider,
			"entries_count", len(entries),
			"linked_count", linkedCount)
	}

	return fjob.NewFromLoadResult(result, entries), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}

