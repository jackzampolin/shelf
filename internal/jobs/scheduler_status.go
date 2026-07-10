package jobs

import (
	"context"
	"fmt"
)

// JobStatus returns the status of a specific job.
func (s *Scheduler) JobStatus(ctx context.Context, jobID string) (map[string]string, error) {
	s.mu.RLock()
	job, ok := s.jobs[jobID]
	pending := s.pending[jobID]
	s.mu.RUnlock()

	if !ok {
		return nil, fmt.Errorf("job not found: %s", jobID)
	}

	status, err := job.Status(ctx)
	if err != nil {
		return nil, err
	}

	if status == nil {
		status = make(map[string]string)
	}
	status["pending_units"] = fmt.Sprintf("%d", pending)

	return status, nil
}

// ActiveJobs returns the number of active jobs.
func (s *Scheduler) ActiveJobs() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.jobs)
}

// PoolStatuses returns status for all pools.
func (s *Scheduler) PoolStatuses() map[string]PoolStatus {
	s.mu.RLock()
	defer s.mu.RUnlock()

	status := make(map[string]PoolStatus, len(s.pools))
	for name, p := range s.pools {
		status[name] = p.Status()
	}
	return status
}

// WorkerStatus returns queue depth and rate limiter status for all pools.
// Deprecated: Use PoolStatuses() for the new format.
// This method is kept for backward compatibility with existing API consumers.
func (s *Scheduler) WorkerStatus() map[string]WorkerStatusInfo {
	return s.WorkerStatusForJob("")
}

// WorkerStatusForJob includes global pool load plus the queried job's exact
// queued, claimed/in-flight, and parked unit counts.
func (s *Scheduler) WorkerStatusForJob(jobID string) map[string]WorkerStatusInfo {
	s.mu.RLock()
	defer s.mu.RUnlock()

	status := make(map[string]WorkerStatusInfo, len(s.pools))
	for name, p := range s.pools {
		ps := p.Status()
		status[name] = WorkerStatusInfo{
			Type:        ps.Type,
			Workers:     ps.Workers,
			InFlight:    ps.InFlight,
			QueueDepth:  ps.QueueDepth,
			Health:      ps.Health,
			ParkedUnits: ps.ParkedUnits,
			RateLimiter: ps.RateLimiter,
		}
		if perJob, ok := p.(JobWorkStatusProvider); ok && jobID != "" {
			jobStatus := perJob.JobWorkStatus(jobID)
			entry := status[name]
			entry.JobQueued = jobStatus.Queued
			entry.JobInFlight = jobStatus.InFlight
			entry.JobParked = jobStatus.Parked
			status[name] = entry
		}
	}
	return status
}

// WorkerStatusInfo reports a worker's current state.
// Deprecated: Use PoolStatus instead.
type WorkerStatusInfo struct {
	Type        string             `json:"type"`
	Workers     int                `json:"workers"`
	InFlight    int                `json:"in_flight"`
	QueueDepth  int                `json:"queue_depth"`
	Health      string             `json:"health,omitempty"`
	ParkedUnits int                `json:"parked_units,omitempty"`
	JobQueued   int                `json:"job_queued"`
	JobInFlight int                `json:"job_in_flight"`
	JobParked   int                `json:"job_parked"`
	RateLimiter *RateLimiterStatus `json:"rate_limiter,omitempty"`
}

// JobProgress returns the per-provider progress for a specific job.
// Returns nil if job is not found.
func (s *Scheduler) JobProgress(jobID string) map[string]ProviderProgress {
	s.mu.RLock()
	job, ok := s.jobs[jobID]
	s.mu.RUnlock()

	if !ok {
		return nil
	}

	return job.Progress()
}
