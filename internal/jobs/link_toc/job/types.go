package job

import (
	"github.com/jackzampolin/shelf/internal/agent"
	toc_entry_finder "github.com/jackzampolin/shelf/internal/agents/toc_entry_finder"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

// MaxRetries is the maximum number of retries for link ToC operations.
const MaxRetries = 3

// WorkUnitType constants.
const (
	WorkUnitTypeEntryFinder = "entry_finder"
)

// WorkUnitInfo tracks pending work units.
type WorkUnitInfo struct {
	UnitType   string
	EntryDocID string // TocEntry document ID being processed
	RetryCount int
}

// Job runs ToC entry linking for a book.
// Requires ToC extraction to be complete (TocEntry records exist).
type Job struct {
	common.TrackedBaseJob[WorkUnitInfo]

	// ToC-specific state
	TocDocID string

	// Entry state
	Entries         []*toc_entry_finder.TocEntry // All entries to process
	EntryAgents     map[string]*agent.Agent      // EntryDocID -> Agent
	EntriesComplete int                          // Count of completed entries
	EntriesFound    int                          // Count of entries with actual_page found

	// Control flags
	Force bool // If true, reset state and re-run even if already complete
}

// NewFromLoadResult creates a Job from a common.LoadBookResult.
// Entries are taken from BookState.TocEntries (loaded during LoadBook).
// If force is true, the job will reset state and re-run even if already complete.
func NewFromLoadResult(result *common.LoadBookResult, force bool) *Job {
	return &Job{
		TrackedBaseJob: common.NewTrackedBaseJob[WorkUnitInfo](result.Book),
		TocDocID:       result.TocDocID,
		Entries:        result.Book.GetTocEntries(),
		EntryAgents:    make(map[string]*agent.Agent),
		Force:          force,
	}
}

// Type returns the job type identifier.
func (j *Job) Type() string {
	return "link-toc"
}

// MetricsFor returns base metrics attribution for this job.
func (j *Job) MetricsFor() *jobs.WorkUnitMetrics {
	return j.BaseJob.MetricsFor(j.Type())
}
