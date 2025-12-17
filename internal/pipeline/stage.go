package pipeline

import (
	"context"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// Stage is the interface that all pipeline stages must implement.
// Stages are the core abstraction - each transforms data and tracks progress.
type Stage interface {
	// Identity
	Name() string           // e.g., "ocr-pages", "extract-toc"
	Dependencies() []string // Stages that must complete first

	// Metadata
	Icon() string
	Description() string

	// RequiredCollections returns the DefraDB collections this stage needs.
	// Used to ensure schemas exist before running.
	RequiredCollections() []string

	// GetStatus queries DefraDB for current stage status.
	// Each stage returns its own status type implementing StageStatus.
	GetStatus(ctx context.Context, bookID string) (StageStatus, error)

	// CreateJob returns a job ready to submit to the scheduler.
	// Internally queries DefraDB to determine remaining work.
	CreateJob(ctx context.Context, bookID string, opts StageOptions) (jobs.Job, error)
}

// StageStatus is implemented by each stage's status type.
// Each stage defines its own struct with stage-specific fields.
type StageStatus interface {
	// IsComplete returns whether this stage is done for this book.
	IsComplete() bool

	// Data returns stage-specific structured data.
	// The shape depends on the stage implementation.
	Data() any
}

// StageOptions configures stage job creation.
// Currently minimal - add fields as specific needs emerge.
type StageOptions map[string]any
