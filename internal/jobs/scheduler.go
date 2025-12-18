package jobs

import (
	"context"
	"log/slog"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
)

// JobFactory creates a Job instance from stored metadata.
// Used for resuming jobs after restart.
type JobFactory func(id string, metadata map[string]any) (Job, error)

// Scheduler manages workers and distributes work units from jobs.
// Each worker runs as its own goroutine with its own queue.
// The scheduler routes work units to appropriate workers and handles results.
type Scheduler struct {
	mu      sync.RWMutex
	manager *Manager                   // For persistence
	workers map[string]WorkerInterface // all workers by name
	jobs    map[string]Job             // active jobs by ID
	logger  *slog.Logger

	// CPU workers for round-robin distribution
	cpuWorkers []*CPUWorker
	cpuIndex   int // next CPU worker to use

	// Job factories for resumption
	factories map[string]JobFactory

	// Results channel - all workers send results here
	results chan workerResult

	// Track pending work per job
	pending map[string]int // jobID -> count of pending work units

	// Running state
	running bool

	// Sink for fire-and-forget metrics writes (passed to workers)
	sink *defra.Sink
}

// SchedulerConfig configures a new scheduler.
type SchedulerConfig struct {
	Manager *Manager // Required for persistence
	Logger  *slog.Logger
	Sink    *defra.Sink // Optional - enables fire-and-forget metrics recording
}

// NewScheduler creates a new scheduler.
func NewScheduler(cfg SchedulerConfig) *Scheduler {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	return &Scheduler{
		manager:    cfg.Manager,
		workers:    make(map[string]WorkerInterface),
		cpuWorkers: make([]*CPUWorker, 0),
		jobs:       make(map[string]Job),
		factories:  make(map[string]JobFactory),
		pending:    make(map[string]int),
		results:    make(chan workerResult, 1000), // Buffered results channel
		logger:     logger,
		sink:       cfg.Sink,
	}
}

// Start begins the scheduler and all registered workers.
// Blocks until context is cancelled.
func (s *Scheduler) Start(ctx context.Context) {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return
	}
	s.running = true

	// Start all workers
	for _, w := range s.workers {
		go w.Start(ctx)
	}
	s.mu.Unlock()

	s.logger.Info("scheduler started", "workers", len(s.workers))

	// Process results from workers
	for {
		select {
		case <-ctx.Done():
			s.logger.Info("scheduler stopping")
			s.mu.Lock()
			s.running = false
			s.mu.Unlock()
			return

		case wr := <-s.results:
			s.handleResult(ctx, wr)
		}
	}
}

// handleResult processes a work result and notifies the job.
func (s *Scheduler) handleResult(ctx context.Context, wr workerResult) {
	s.mu.Lock()
	job, ok := s.jobs[wr.JobID]
	if ok {
		s.pending[wr.JobID]--
	}
	s.mu.Unlock()

	if !ok {
		s.logger.Warn("received result for unknown job", "job_id", wr.JobID)
		return
	}

	// Notify job of completion
	newUnits, err := job.OnComplete(ctx, wr.Result)
	if err != nil {
		s.logger.Error("job OnComplete failed", "job_id", wr.JobID, "error", err)
	}

	// Enqueue any new work units
	if len(newUnits) > 0 {
		s.enqueueUnits(wr.JobID, newUnits)
	}

	// Check if job is done
	s.mu.Lock()
	pendingCount := s.pending[wr.JobID]
	isDone := job.Done() && pendingCount == 0
	if isDone {
		delete(s.jobs, wr.JobID)
		delete(s.pending, wr.JobID)
	}
	s.mu.Unlock()

	if isDone {
		s.logger.Info("job completed", "id", job.ID(), "type", job.Type())

		// Update DefraDB status
		if s.manager != nil {
			if err := s.manager.UpdateStatus(ctx, job.ID(), StatusCompleted, ""); err != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", err)
			}
		}
	}
}
