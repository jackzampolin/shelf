package metadata_book

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	mjob "github.com/jackzampolin/shelf/internal/jobs/metadata_book/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "metadata-book"

// Config configures the metadata book job.
type Config struct {
	MetadataProvider string
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.MetadataProvider == "" {
		return fmt.Errorf("metadata provider is required")
	}
	return nil
}

// NewJob creates a new metadata book job for the given book.
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
		HomeDir:          homeDir,
		MetadataProvider: cfg.MetadataProvider,
		PromptKeys:       mjob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating metadata book job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"metadata_provider", cfg.MetadataProvider,
			"metadata_complete", result.Book.Metadata.IsComplete())
	}

	return mjob.NewFromLoadResult(result), nil
}

// JobFactory returns a factory function for recreating jobs from stored metadata.
func JobFactory(cfg Config) jobs.JobFactory {
	return func(ctx context.Context, id string, metadata map[string]any) (jobs.Job, error) {
		bookID, ok := metadata["book_id"].(string)
		if !ok {
			return nil, fmt.Errorf("missing book_id in job metadata")
		}

		job, err := NewJob(ctx, cfg, bookID)
		if err != nil {
			return nil, err
		}

		job.SetRecordID(id)
		return job, nil
	}
}
