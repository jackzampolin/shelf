package common

import (
	"sync"

	"github.com/jackzampolin/shelf/internal/jobs"
)

// JobContext provides access to common job properties needed by work unit creators.
// Jobs that embed BaseJob and implement Type() automatically satisfy this interface.
type JobContext interface {
	GetBook() *BookState
	ID() string
	Type() string
}

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

// GetBook returns the book state.
// Note: This is not thread-safe for the Book pointer itself, but BookState
// has its own internal synchronization for field access.
func (j *BaseJob) GetBook() *BookState {
	return j.Book
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

// TrackedBaseJob extends BaseJob with generic work unit tracking.
// This eliminates boilerplate Register/Get/RemoveWorkUnit methods from job implementations.
//
// Usage:
//
//	type WorkUnitInfo struct {
//	    PageNum    int
//	    UnitType   string
//	    RetryCount int
//	}
//
//	type Job struct {
//	    common.TrackedBaseJob[WorkUnitInfo]
//	    // job-specific fields
//	}
//
//	func (j *Job) Type() string { return "my-job" }
type TrackedBaseJob[T any] struct {
	BaseJob
	Tracker *WorkUnitTracker[T]
}

// NewTrackedBaseJob creates a TrackedBaseJob with an initialized tracker.
func NewTrackedBaseJob[T any](book *BookState) TrackedBaseJob[T] {
	return TrackedBaseJob[T]{
		BaseJob: BaseJob{Book: book},
		Tracker: NewWorkUnitTracker[T](),
	}
}

// RegisterWorkUnit registers a pending work unit.
func (j *TrackedBaseJob[T]) RegisterWorkUnit(unitID string, info T) {
	j.Tracker.Register(unitID, info)
}

// GetWorkUnit gets a pending work unit without removing it.
func (j *TrackedBaseJob[T]) GetWorkUnit(unitID string) (T, bool) {
	return j.Tracker.Get(unitID)
}

// RemoveWorkUnit removes a pending work unit.
func (j *TrackedBaseJob[T]) RemoveWorkUnit(unitID string) {
	j.Tracker.Remove(unitID)
}

// GetAndRemoveWorkUnit gets and removes a pending work unit atomically.
func (j *TrackedBaseJob[T]) GetAndRemoveWorkUnit(unitID string) (T, bool) {
	return j.Tracker.GetAndRemove(unitID)
}

// PendingWorkUnits returns the number of pending work units.
func (j *TrackedBaseJob[T]) PendingWorkUnits() int {
	return j.Tracker.Count()
}
