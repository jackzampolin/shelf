package jobs

import (
	"context"
	"log/slog"
	"sync"

	"github.com/jackzampolin/shelf/internal/defra"
)

// JobFactory creates a Job instance from stored metadata.
// Used for resuming jobs after restart.
// Context provides access to services (DefraClient, HomeDir, etc.) via svcctx.
type JobFactory func(ctx context.Context, id string, metadata map[string]any) (Job, error)

// Scheduler manages worker pools and distributes work units from jobs.
// Each pool runs its own goroutines and manages its own queue.
// The scheduler routes work units to appropriate pools and handles results.
type Scheduler struct {
	mu      sync.RWMutex
	manager *Manager              // For persistence
	pools   map[string]WorkerPool // all pools by name
	cpuPool *CPUWorkerPool        // CPU pool (also in pools map)
	jobs    map[string]Job        // active jobs by ID
	logger  *slog.Logger

	// Job factories for resumption
	factories map[string]JobFactory

	// Results channel - all pools send results here
	results chan workerResult

	// Track pending work per job
	pending map[string]int // jobID -> count of pending work units

	// Running state
	running bool
	ctx     context.Context // Scheduler's long-lived context (set in Start)

	// Sink for fire-and-forget metrics writes (passed to pools)
	sink *defra.Sink

	// Context enricher for async job context injection
	contextEnricher func(context.Context) context.Context
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
		manager:   cfg.Manager,
		pools:     make(map[string]WorkerPool),
		jobs:      make(map[string]Job),
		factories: make(map[string]JobFactory),
		pending:   make(map[string]int),
		results:   make(chan workerResult, 1000), // Buffered results channel
		logger:    logger,
		sink:      cfg.Sink,
	}
}

// SetContextEnricher sets a callback for enriching job contexts with services.
// Must be called after creating the Services struct but before submitting jobs.
// The enricher callback adds services (DefraClient, Sink, Logger, etc.) to the context.
func (s *Scheduler) SetContextEnricher(enricher func(context.Context) context.Context) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.contextEnricher = enricher
}

// removeJob removes a job from the scheduler's tracking maps.
// Thread-safe: acquires lock internally.
func (s *Scheduler) removeJob(jobID string) {
	s.mu.Lock()
	delete(s.jobs, jobID)
	delete(s.pending, jobID)
	s.mu.Unlock()
}

// Start begins the scheduler and all registered pools.
// Blocks until context is cancelled.
func (s *Scheduler) Start(ctx context.Context) {
	s.mu.Lock()
	if s.running {
		s.mu.Unlock()
		return
	}
	s.running = true
	s.ctx = ctx // Store for async job operations

	// Start all pools
	for _, p := range s.pools {
		go p.Start(ctx)
	}
	s.mu.Unlock()

	s.logger.Info("scheduler started", "pools", len(s.pools))

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

	// Inject services into context for job handlers
	enrichedCtx := s.injectServices(ctx)

	// Notify job of completion
	newUnits, err := job.OnComplete(enrichedCtx, wr.Result)
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
