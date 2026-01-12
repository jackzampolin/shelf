package job

import (
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// MaxPageOpRetries is the maximum number of retries for page-level operations.
const MaxPageOpRetries = 3

// BookStatus represents the top-level status of a book.
type BookStatus string

const (
	BookStatusProcessing BookStatus = "processing"
	BookStatusComplete   BookStatus = "complete"
)

// WorkUnitType constants.
const (
	WorkUnitTypeLabel = "label"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	PageNum    int
	UnitType   string
	RetryCount int
}

// PageState is an alias for common.PageState.
type PageState = common.PageState

// Job processes all pages through the Label stage.
// Requires pages to already have blend_complete.
type Job struct {
	common.TrackedBaseJob[WorkUnitInfo]
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
func NewFromLoadResult(result *common.LoadBookResult) *Job {
	return &Job{
		TrackedBaseJob: common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "label-book"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}

// AllPagesLabelComplete returns true if all pages have completed labeling.
func (j *Job) AllPagesLabelComplete() bool {
	allDone := true
	j.Book.ForEachPage(func(pageNum int, state *PageState) {
		if !state.IsLabelDone() {
			allDone = false
		}
	})
	return allDone && j.Book.CountPages() >= j.Book.TotalPages
}
