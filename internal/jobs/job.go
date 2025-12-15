package jobs

import (
	"context"
	"log/slog"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// Job is the interface that all job types must implement.
type Job interface {
	// Type returns the job type identifier.
	Type() string

	// Execute runs the job. It should respect context cancellation.
	// Dependencies are retrieved via DepsFromContext(ctx).
	//
	// IMPORTANT: Execute must be idempotent. Jobs may be resumed after
	// server restarts, crashes, or failures. The implementation must:
	// - Check existing state before starting work
	// - Handle partial completion gracefully
	// - Not assume a clean starting state
	// - Use the job's metadata to track progress
	Execute(ctx context.Context) error

	// Status returns the current status of the job as key-value pairs.
	// This allows jobs to report progress, current step, items processed, etc.
	// Returns nil map if no status to report.
	Status(ctx context.Context) (map[string]string, error)
}

// Dependencies provides access to shared resources for job execution.
type Dependencies struct {
	DefraClient *defra.Client
	Logger      *slog.Logger
}

// depsKey is the context key for Dependencies.
type depsKey struct{}

// ContextWithDeps returns a new context with Dependencies attached.
func ContextWithDeps(ctx context.Context, deps Dependencies) context.Context {
	return context.WithValue(ctx, depsKey{}, deps)
}

// DepsFromContext retrieves Dependencies from the context.
// Returns a Dependencies with nil fields if not found.
func DepsFromContext(ctx context.Context) Dependencies {
	deps, ok := ctx.Value(depsKey{}).(Dependencies)
	if !ok {
		return Dependencies{}
	}
	return deps
}

// Status represents the current state of a job.
type Status string

const (
	StatusQueued    Status = "queued"
	StatusRunning   Status = "running"
	StatusCompleted Status = "completed"
	StatusFailed    Status = "failed"
	StatusCancelled Status = "cancelled"
)

// Record represents a job record stored in DefraDB.
// This maps to the Job schema.
type Record struct {
	ID          string         `json:"_docID,omitempty"`
	JobType     string         `json:"job_type"`
	Status      Status         `json:"status"`
	CreatedAt   time.Time      `json:"created_at"`
	StartedAt   *time.Time     `json:"started_at,omitempty"`
	CompletedAt *time.Time     `json:"completed_at,omitempty"`
	Error       string         `json:"error,omitempty"`
	Metadata    map[string]any `json:"metadata,omitempty"`
}

// NewRecord creates a new job record for submission.
func NewRecord(jobType string, metadata map[string]any) *Record {
	return &Record{
		JobType:   jobType,
		Status:    StatusQueued,
		CreatedAt: time.Now().UTC(),
		Metadata:  metadata,
	}
}
