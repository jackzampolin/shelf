package job

import (
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
	common.BaseJob
	Tracker *common.WorkUnitTracker[WorkUnitInfo]
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		BaseJob: common.BaseJob{
			Book: result.Book,
		},
		Tracker: common.NewWorkUnitTracker[WorkUnitInfo](),
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "metadata-book"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}

// RegisterWorkUnit registers a pending work unit.
func (j *Job) RegisterWorkUnit(unitID string, info WorkUnitInfo) {
	j.Tracker.Register(unitID, info)
}

// GetWorkUnit gets a pending work unit without removing it.
func (j *Job) GetWorkUnit(unitID string) (WorkUnitInfo, bool) {
	return j.Tracker.Get(unitID)
}

// RemoveWorkUnit removes a pending work unit.
func (j *Job) RemoveWorkUnit(unitID string) {
	j.Tracker.Remove(unitID)
}
