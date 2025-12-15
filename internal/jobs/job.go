package jobs

import (
	"context"
	"errors"
	"log/slog"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ErrNotFound is returned when a job is not found.
var ErrNotFound = errors.New("job not found")

// WorkUnitType distinguishes LLM from OCR work.
type WorkUnitType string

const (
	WorkUnitTypeLLM WorkUnitType = "llm"
	WorkUnitTypeOCR WorkUnitType = "ocr"
)

// WorkUnit is a single unit of work for a provider.
type WorkUnit struct {
	ID       string       // Unique identifier for this work unit
	Type     WorkUnitType // "llm" or "ocr"
	Provider string       // Specific provider name, or "" for any of this type
	JobID    string       // Which job this belongs to
	Priority int          // Higher = processed first

	// Request data (one of these will be set based on Type)
	ChatRequest *providers.ChatRequest
	OCRRequest  *OCRWorkRequest
}

// OCRWorkRequest contains the data needed for an OCR work unit.
type OCRWorkRequest struct {
	Image   []byte
	PageNum int
}

// WorkResult is the result of a completed work unit.
type WorkResult struct {
	WorkUnitID string
	Success    bool
	Error      error

	// Result data (one of these will be set based on work unit type)
	ChatResult *providers.ChatResult
	OCRResult  *providers.OCRResult
}

// Job is the interface that all job types must implement.
// Jobs dynamically create work units and react to their completion.
type Job interface {
	// ID returns the unique job identifier.
	ID() string

	// Type returns the job type identifier.
	Type() string

	// Start initializes the job and returns the initial work units to enqueue.
	// Called once when the job begins execution.
	Start(ctx context.Context) ([]WorkUnit, error)

	// OnComplete is called when a work unit finishes.
	// Returns NEW work units to enqueue (e.g., LLM work after OCR completes).
	// This is how jobs implement multi-phase workflows.
	OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error)

	// Done returns true when the job has no more pending work units
	// and all work has completed.
	Done() bool

	// Status returns the current status of the job as key-value pairs.
	// This allows jobs to report progress, current step, items processed, etc.
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
