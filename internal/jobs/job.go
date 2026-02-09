package jobs

import (
	"context"
	"errors"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

// Sentinel errors for the jobs package.
var (
	// ErrNotFound is returned when a job is not found.
	ErrNotFound = errors.New("job not found")

	// ErrNoWorkerAvailable is returned when no worker can handle a work unit.
	ErrNoWorkerAvailable = errors.New("no worker available")

	// ErrWorkerQueueFull is returned when a worker's queue is at capacity.
	ErrWorkerQueueFull = errors.New("worker queue full")

	// ErrJobAlreadyStarted is returned when trying to start an already-running job.
	ErrJobAlreadyStarted = errors.New("job already started")

	// ErrManagerRequired is returned when an operation requires a manager but none is set.
	ErrManagerRequired = errors.New("manager required")
)

// WorkUnitType distinguishes work by resource type.
type WorkUnitType string

const (
	WorkUnitTypeLLM WorkUnitType = "llm"
	WorkUnitTypeOCR WorkUnitType = "ocr"
	WorkUnitTypeTTS WorkUnitType = "tts"
	WorkUnitTypeCPU WorkUnitType = "cpu" // CPU-bound work (no rate limiting)
)

// WorkUnit is a single unit of work for a provider.
type WorkUnit struct {
	ID       string       // Unique identifier for this work unit
	Type     WorkUnitType // "llm", "ocr", "tts", or "cpu"
	Provider string       // Specific provider name, or "" for any of this type
	JobID    string       // Which job this belongs to
	Priority int          // Higher = processed first

	// Request data (one of these will be set based on Type)
	ChatRequest *providers.ChatRequest
	OCRRequest  *OCRWorkRequest
	TTSRequest  *TTSWorkRequest
	CPURequest  *CPUWorkRequest

	// Tools for LLM calls (optional - if set, ChatWithTools is used)
	Tools []providers.Tool

	// Metrics attribution (used by workers for automatic metrics recording)
	Metrics *WorkUnitMetrics
}

// WorkUnitMetrics provides attribution data for metrics recording.
// Set these fields on work units to enable automatic metrics recording by workers.
type WorkUnitMetrics struct {
	BookID    string // Book being processed
	PageID    string // Page being processed (if applicable)
	Stage     string // Pipeline stage (e.g., "page-processing")
	ItemKey   string // Item identifier (e.g., "page_0001", "toc_entry_5")
	PromptKey string // Prompt identifier for LLM call tracing (e.g., "stages.blend.system")
	PromptCID string // Content-addressed ID of the exact prompt version used
}

// OCRWorkRequest contains the data needed for an OCR work unit.
type OCRWorkRequest struct {
	Image   []byte
	PageNum int
}

// TTSWorkRequest contains the data needed for a TTS work unit.
type TTSWorkRequest struct {
	Text         string // Text to convert to speech
	Voice        string // Voice ID or name (provider-specific)
	Format       string // Output format (mp3, wav, etc.)
	Instructions string // Optional provider-specific instructions (OpenAI gpt-4o-mini-tts)
	ChapterIdx   int    // Chapter index for reference
	ParagraphIdx int    // Paragraph index within chapter

	// Request stitching for prosody continuity (ElevenLabs).
	// Pass up to 3 previous request IDs from prior segments in this chapter.
	PreviousRequestIDs []string
}

// CPUWorkRequest contains the data needed for a CPU-bound work unit.
// The Task field identifies what kind of CPU work this is.
type CPUWorkRequest struct {
	Task string // Task identifier (e.g., "extract-page")
	Data any    // Task-specific data
}

// WorkResult is the result of a completed work unit.
type WorkResult struct {
	WorkUnitID  string
	Success     bool
	Error       error
	MetricDocID string // DefraDB Metric doc ID (if recorded)

	// Result data (one of these will be set based on work unit type)
	ChatResult *providers.ChatResult
	OCRResult  *providers.OCRResult
	TTSResult  *providers.TTSResult
	CPUResult  *CPUWorkResult
}

// CPUWorkResult contains the result of a CPU-bound work unit.
type CPUWorkResult struct {
	Data any // Task-specific result data
}

// ProviderProgress tracks work unit progress for a single provider.
// This enables granular progress tracking during job execution.
type ProviderProgress struct {
	TotalExpected    int // Total work units expected for this provider
	CompletedAtStart int // Already completed before job started (from DefraDB)
	Queued           int // Currently queued/in-flight
	Completed        int // Completed during this job execution
	Failed           int // Failed during this job execution
}

// Remaining returns work units not yet processed.
func (p ProviderProgress) Remaining() int {
	return p.TotalExpected - p.CompletedAtStart - p.Completed - p.Failed
}

// PercentComplete returns overall completion percentage (0-100).
func (p ProviderProgress) PercentComplete() float64 {
	if p.TotalExpected == 0 {
		return 0
	}
	done := p.CompletedAtStart + p.Completed
	return float64(done) / float64(p.TotalExpected) * 100
}

// Job is the interface that all job types must implement.
// Jobs dynamically create work units and react to their completion.
type Job interface {
	// ID returns the DefraDB record ID for this job.
	// Returns empty string before SetRecordID is called.
	ID() string

	// SetRecordID sets the DefraDB record ID after the job is persisted.
	// This is called by the scheduler after creating the job in DefraDB.
	SetRecordID(id string)

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

	// Progress returns per-provider work unit progress.
	// Keys are provider names (e.g., "openrouter", "mistral").
	// This enables granular progress tracking during execution.
	Progress() map[string]ProviderProgress

	// MetricsFor returns base metrics attribution for this job.
	// Returns BookID and Stage pre-filled. Callers add ItemKey for specific work units.
	MetricsFor() *WorkUnitMetrics
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

// BookIDProvider is implemented by jobs that process a specific book.
// Used by Scheduler.GetJobByBookID to find active jobs.
type BookIDProvider interface {
	BookID() string
}

// LiveStatusProvider is implemented by jobs that can provide real-time
// status from in-memory state, avoiding database queries during execution.
type LiveStatusProvider interface {
	// LiveStatus returns current processing status from in-memory state.
	// This is faster and more up-to-date than querying DefraDB.
	LiveStatus() *LiveStatus
}

// LiveStatus contains real-time status from a running job's in-memory state.
type LiveStatus struct {
	TotalPages        int
	OcrComplete       int
	MetadataComplete  bool
	TocFound          bool
	TocExtracted      bool
	TocLinked         bool
	TocFinalized      bool
	StructureStarted  bool
	StructureComplete bool

	// Cost tracking (from write-through cache)
	TotalCostUSD float64
	CostsByStage map[string]float64

	// Agent run tracking (from write-through cache)
	AgentRunCount int
}

// Record represents a job record stored in DefraDB.
// This maps to the Job schema.
type Record struct {
	ID          string         `json:"_docID,omitempty"`
	JobType     string         `json:"job_type"`
	BookID      string         `json:"book_id,omitempty"`
	Status      Status         `json:"status"`
	CreatedAt   time.Time      `json:"created_at"`
	StartedAt   *time.Time     `json:"started_at,omitempty"`
	CompletedAt *time.Time     `json:"completed_at,omitempty"`
	Error       string         `json:"error,omitempty"`
	Metadata    map[string]any `json:"metadata,omitempty"`
}

// Duration returns the job duration if started and completed.
func (r *Record) Duration() *float64 {
	if r.StartedAt == nil || r.CompletedAt == nil {
		return nil
	}
	d := r.CompletedAt.Sub(*r.StartedAt).Seconds()
	return &d
}

// NewRecord creates a new job record for submission.
func NewRecord(jobType string, metadata map[string]any) *Record {
	// Extract book_id from metadata if present
	var bookID string
	if metadata != nil {
		if bid, ok := metadata["book_id"].(string); ok {
			bookID = bid
		}
	}
	return &Record{
		JobType:   jobType,
		BookID:    bookID,
		Status:    StatusQueued,
		CreatedAt: time.Now().UTC(),
		Metadata:  metadata,
	}
}
