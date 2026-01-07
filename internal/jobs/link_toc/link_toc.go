package link_toc

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	ljob "github.com/jackzampolin/shelf/internal/jobs/link_toc/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "link-toc"

// Config configures the link toc job.
type Config struct {
	TocProvider string
	DebugAgents bool
	Force       bool // If true, reset state and re-run even if already complete
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.TocProvider == "" {
		return fmt.Errorf("toc provider is required")
	}
	return nil
}

// NewJob creates a new link toc job for the given book.
func NewJob(ctx context.Context, cfg Config, bookID string) (jobs.Job, error) {
	if err := cfg.Validate(); err != nil {
		return nil, fmt.Errorf("invalid config: %w", err)
	}

	homeDir := svcctx.HomeFrom(ctx)
	if homeDir == nil {
		return nil, fmt.Errorf("home directory not in context")
	}

	// Load everything about this book
	result, err := common.LoadBook(ctx, bookID, common.LoadBookConfig{
		HomeDir:     homeDir,
		TocProvider: cfg.TocProvider,
		DebugAgents: cfg.DebugAgents,
		PromptKeys:  ljob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	// Verify preconditions: ToC extraction must be complete
	if !result.Book.TocExtract.IsComplete() {
		return nil, fmt.Errorf("ToC extraction not complete - cannot link entries")
	}

	// TocEntries are loaded during LoadBook when TocExtract is complete
	entries := result.Book.GetTocEntries()

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating link toc job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"toc_provider", cfg.TocProvider,
			"entries_count", len(entries),
			"force", cfg.Force)
	}

	return ljob.NewFromLoadResult(result, cfg.Force), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return common.MakeJobFactory(func(ctx context.Context, bookID string) (jobs.Job, error) {
		return NewJob(ctx, cfg, bookID)
	})
}
