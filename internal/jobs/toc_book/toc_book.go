package toc_book

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	tjob "github.com/jackzampolin/shelf/internal/jobs/toc_book/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "toc-book"

// Config configures the toc book job.
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

// NewJob creates a new toc book job for the given book.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Load everything about this book in one call
	result, err := common.LoadBook(ctx, bookID, common.LoadBookConfig{
		HomeDir:     homeDir,
		TocProvider: cfg.TocProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  tjob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating toc book job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"toc_provider", cfg.TocProvider,
			"toc_finder_complete", result.Book.TocFinder.IsComplete(),
			"toc_extract_complete", result.Book.TocExtract.IsComplete())
	}

	return tjob.NewFromLoadResult(result), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}
