package label_book

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
	ljob "github.com/jackzampolin/shelf/internal/jobs/label_book/job"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// JobType is the identifier for this job type.
const JobType = "label-book"

// Config configures the label book job.
type Config struct {
	LabelProvider string
}

// Validate checks that the config has all required fields.
func (c Config) Validate() error {
	if c.LabelProvider == "" {
		return fmt.Errorf("label provider is required")
	}
	return nil
}

// Status represents the status of label processing for a book.
type Status struct {
	TotalPages    int `json:"total_pages"`
	BlendComplete int `json:"blend_complete"`
	LabelComplete int `json:"label_complete"`
}

// IsComplete returns whether label processing is complete for this book.
func (st *Status) IsComplete() bool {
	return st.LabelComplete >= st.TotalPages
}

// NewJob creates a new label book job for the given book.
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
		HomeDir:       homeDir,
		LabelProvider: cfg.LabelProvider,
		PromptKeys:    ljob.PromptKeys(),
	})
	if err != nil {
		return nil, fmt.Errorf("failed to load book: %w", err)
	}

	logger := svcctx.LoggerFrom(ctx)
	if logger != nil {
		logger.Info("creating label book job",
			"book_id", bookID,
			"total_pages", result.Book.TotalPages,
			"label_provider", cfg.LabelProvider)
	}

	return ljob.NewFromLoadResult(result), nil
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
