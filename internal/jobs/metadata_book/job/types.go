package job

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// MaxRetries is the maximum number of retries for metadata extraction.
const MaxRetries = 3

// WorkUnitType constants.
const (
	WorkUnitTypeMetadata = "metadata"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	UnitType   string
	RetryCount int
}

// Job extracts metadata from a book.
// Requires pages to already have blend_complete (uses first N pages of text).
type Job struct {
	mu sync.Mutex

	// Book state
	Book *common.BookState

	// Job-specific state
	RecordID string
	IsDone   bool

	// Work unit tracking
	PendingUnits map[string]WorkUnitInfo
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		Book:         result.Book,
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
		Stage:  "metadata-book",
	}
}
