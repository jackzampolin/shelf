package job

import (
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
	common.TrackedBaseJob[WorkUnitInfo]

	// ToC-specific state
	TocDocID string
	TocAgent *agent.Agent
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		TrackedBaseJob: common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
		TocDocID:       result.TocDocID,
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "toc-book"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}
