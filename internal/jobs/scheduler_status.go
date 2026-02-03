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
	s.mu.RLock()
	defer s.mu.RUnlock()

	status := make(map[string]WorkerStatusInfo, len(s.pools))
	for name, p := range s.pools {
		ps := p.Status()
		status[name] = WorkerStatusInfo{
			Type:        ps.Type,
			QueueDepth:  ps.QueueDepth,
			RateLimiter: ps.RateLimiter,
		}
	}
	return status
}

// WorkerStatusInfo reports a worker's current state.
// Deprecated: Use PoolStatus instead.
type WorkerStatusInfo struct {
	Type        string             `json:"type"`
	QueueDepth  int                `json:"queue_depth"`
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
