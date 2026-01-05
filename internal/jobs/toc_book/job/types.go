package job

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/agent"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// MaxRetries is the maximum number of retries for ToC operations.
const MaxRetries = 3

// WorkUnitType constants.
const (
	WorkUnitTypeTocFinder  = "toc_finder"
	WorkUnitTypeTocExtract = "toc_extract"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	UnitType   string
	RetryCount int
}

// Job runs ToC finder and extraction for a book.
// Requires pages to already have blend_complete (uses labeled pages for ToC finding).
type Job struct {
	mu sync.Mutex

	// Book state
	Book *common.BookState

	// Job-specific state
	RecordID string
	IsDone   bool
	TocDocID string

	// Agent state (for multi-turn ToC finder)
	TocAgent *agent.Agent

	// Work unit tracking
	PendingUnits map[string]WorkUnitInfo
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		Book:         result.Book,
		TocDocID:     result.TocDocID,
		PendingUnits: make(map[string]WorkUnitInfo),
	}
}

// RegisterWorkUnit registers a pending work unit.
func (j *Job) RegisterWorkUnit(unitID string, info WorkUnitInfo) {
	j.PendingUnits[unitID] = info
}

// GetWorkUnit gets a pending work unit without removing it.
func (j *Job) GetWorkUnit(unitID string) (WorkUnitInfo, bool) {
	info, ok := j.PendingUnits[unitID]
	return info, ok
}

// RemoveWorkUnit removes a pending work unit.
func (j *Job) RemoveWorkUnit(unitID string) {
	delete(j.PendingUnits, unitID)
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return &jobs.WorkUnitMetrics{
		BookID: j.Book.BookID,
		Stage:  "toc-book",
	}
}
