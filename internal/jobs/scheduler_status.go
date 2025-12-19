package jobs

import (
	"context"
	"fmt"

	"github.com/jackzampolin/shelf/internal/providers"
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

// WorkerStatus returns queue depth and rate limiter status for all workers.
func (s *Scheduler) WorkerStatus() map[string]WorkerStatusInfo {
	s.mu.RLock()
	defer s.mu.RUnlock()

	status := make(map[string]WorkerStatusInfo, len(s.workers))
	for name, w := range s.workers {
		info := WorkerStatusInfo{
			Type:       string(w.Type()),
			QueueDepth: w.QueueDepth(),
		}
		// Only LLM/OCR workers have rate limiters
		if rw, ok := w.(*ProviderWorker); ok {
			rlStatus := rw.RateLimiterStatus()
			info.RateLimiter = &rlStatus
		}
		status[name] = info
	}
	return status
}

// WorkerStatusInfo reports a worker's current state.
type WorkerStatusInfo struct {
	Type        string                       `json:"type"`
	QueueDepth  int                          `json:"queue_depth"`
	RateLimiter *providers.RateLimiterStatus `json:"rate_limiter,omitempty"`
}
