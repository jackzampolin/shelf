package common

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// BaseJob provides common job functionality that can be embedded in specific jobs.
// Embedding jobs must still provide their own Type() method.
//
// Usage:
//
//	type Job struct {
//	    common.BaseJob
//	    // job-specific fields
//	}
//
//	func (j *Job) Type() string { return "my-job" }
type BaseJob struct {
	Mu       sync.Mutex
	Book     *BookState
	RecordID string
	IsDone   bool
}

// ID returns the job record ID (thread-safe).
func (j *BaseJob) ID() string {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.RecordID
}

// SetRecordID sets the job record ID (thread-safe).
func (j *BaseJob) SetRecordID(id string) {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	j.RecordID = id
}

// Done returns true if the job is complete (thread-safe).
func (j *BaseJob) Done() bool {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	return j.IsDone
}

// MarkDone marks the job as complete (thread-safe).
// This is a helper for jobs that need to set IsDone while holding their own lock.
func (j *BaseJob) MarkDone() {
	j.Mu.Lock()
	defer j.Mu.Unlock()
	j.IsDone = true
}

// MetricsFor returns base metrics for work units.
// Stage parameter allows job-specific stage name.
func (j *BaseJob) MetricsFor(stage string) *jobs.WorkUnitMetrics {
	return &jobs.WorkUnitMetrics{
		BookID: j.Book.BookID,
		Stage:  stage,
	}
}

// ProviderProgress returns progress by provider.
func (j *BaseJob) ProviderProgress() map[string]jobs.ProviderProgress {
	bookProgress := j.Book.GetProviderProgress()
	progress := make(map[string]jobs.ProviderProgress, len(bookProgress))
	for key, p := range bookProgress {
		progress[key] = jobs.ProviderProgress{
			TotalExpected: p.TotalExpected,
			Completed:     p.Completed,
		}
	}
	return progress
}
