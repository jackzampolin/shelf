package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
)

// Scheduler manages workers and distributes work units from jobs.
type Scheduler struct {
	mu      sync.RWMutex
	workers map[string]*Worker // workers by name
	jobs    map[string]Job     // active jobs by ID
	logger  *slog.Logger

	// Work queue (buffered channel)
	queue chan *WorkUnit

	// Track pending work per job
	pending map[string]int // jobID -> count of pending work units
}

// SchedulerConfig configures a new scheduler.
type SchedulerConfig struct {
	Logger    *slog.Logger
	QueueSize int // Size of work queue buffer (default 1000)
}

// NewScheduler creates a new scheduler.
func NewScheduler(cfg SchedulerConfig) *Scheduler {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}
	queueSize := cfg.QueueSize
	if queueSize <= 0 {
		queueSize = 1000
	}

	return &Scheduler{
		workers: make(map[string]*Worker),
		jobs:    make(map[string]Job),
		pending: make(map[string]int),
		queue:   make(chan *WorkUnit, queueSize),
		logger:  logger,
	}
}

// RegisterWorker adds a worker to the scheduler.
func (s *Scheduler) RegisterWorker(w *Worker) {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.workers[w.Name()] = w
	s.logger.Info("worker registered", "name", w.Name(), "type", w.Type())
}

// GetWorker returns a worker by name.
func (s *Scheduler) GetWorker(name string) (*Worker, bool) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	w, ok := s.workers[name]
	return w, ok
}

// ListWorkers returns all worker names.
func (s *Scheduler) ListWorkers() []string {
	s.mu.RLock()
	defer s.mu.RUnlock()

	names := make([]string, 0, len(s.workers))
	for name := range s.workers {
		names = append(names, name)
	}
	return names
}

// Submit starts a job and enqueues its initial work units.
func (s *Scheduler) Submit(ctx context.Context, job Job) error {
	s.mu.Lock()
	s.jobs[job.ID()] = job
	s.pending[job.ID()] = 0
	s.mu.Unlock()

	s.logger.Info("job submitted", "job_id", job.ID(), "type", job.Type())

	// Start the job to get initial work units
	units, err := job.Start(ctx)
	if err != nil {
		s.mu.Lock()
		delete(s.jobs, job.ID())
		delete(s.pending, job.ID())
		s.mu.Unlock()
		return fmt.Errorf("job start failed: %w", err)
	}

	// Enqueue initial work units
	s.enqueueUnits(job.ID(), units)

	return nil
}

// enqueueUnits adds work units to the queue and updates pending count.
func (s *Scheduler) enqueueUnits(jobID string, units []WorkUnit) {
	if len(units) == 0 {
		return
	}

	s.mu.Lock()
	s.pending[jobID] += len(units)
	s.mu.Unlock()

	for i := range units {
		unit := &units[i]
		unit.JobID = jobID
		select {
		case s.queue <- unit:
		default:
			s.logger.Warn("queue full, dropping work unit", "unit_id", unit.ID, "job_id", jobID)
		}
	}

	s.logger.Debug("enqueued work units", "job_id", jobID, "count", len(units))
}

// Run starts the scheduler loop. It processes work units until ctx is cancelled.
// Call this in a goroutine.
func (s *Scheduler) Run(ctx context.Context) {
	s.logger.Info("scheduler started")

	for {
		select {
		case <-ctx.Done():
			s.logger.Info("scheduler stopping")
			return

		case unit := <-s.queue:
			s.processUnit(ctx, unit)
		}
	}
}

// RunWorkers starts multiple worker goroutines to process the queue in parallel.
func (s *Scheduler) RunWorkers(ctx context.Context, numWorkers int) {
	s.logger.Info("starting worker pool", "count", numWorkers)

	var wg sync.WaitGroup
	for i := 0; i < numWorkers; i++ {
		wg.Add(1)
		go func(workerNum int) {
			defer wg.Done()
			s.workerLoop(ctx, workerNum)
		}(i)
	}

	// Wait for all workers to finish when context is cancelled
	go func() {
		<-ctx.Done()
		wg.Wait()
		s.logger.Info("all workers stopped")
	}()
}

func (s *Scheduler) workerLoop(ctx context.Context, workerNum int) {
	logger := s.logger.With("worker_num", workerNum)
	logger.Debug("worker started")

	for {
		select {
		case <-ctx.Done():
			logger.Debug("worker stopping")
			return

		case unit := <-s.queue:
			s.processUnit(ctx, unit)
		}
	}
}

func (s *Scheduler) processUnit(ctx context.Context, unit *WorkUnit) {
	// Find appropriate worker
	worker := s.findWorker(unit)
	if worker == nil {
		s.logger.Error("no worker found for work unit",
			"unit_id", unit.ID,
			"type", unit.Type,
			"provider", unit.Provider,
		)
		s.handleResult(ctx, unit, WorkResult{
			WorkUnitID: unit.ID,
			Success:    false,
			Error:      fmt.Errorf("no worker available for type %s provider %s", unit.Type, unit.Provider),
		})
		return
	}

	// Process the work unit
	result := worker.Process(ctx, unit)

	// Handle the result
	s.handleResult(ctx, unit, result)
}

// findWorker finds an appropriate worker for the work unit.
func (s *Scheduler) findWorker(unit *WorkUnit) *Worker {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// If specific provider requested, use that
	if unit.Provider != "" {
		if w, ok := s.workers[unit.Provider]; ok {
			// Verify type matches
			if (unit.Type == WorkUnitTypeLLM && w.Type() == WorkerTypeLLM) ||
				(unit.Type == WorkUnitTypeOCR && w.Type() == WorkerTypeOCR) {
				return w
			}
		}
		return nil
	}

	// Otherwise find any worker of the right type
	targetType := WorkerTypeLLM
	if unit.Type == WorkUnitTypeOCR {
		targetType = WorkerTypeOCR
	}

	for _, w := range s.workers {
		if w.Type() == targetType {
			return w
		}
	}

	return nil
}

// handleResult processes a work result and notifies the job.
func (s *Scheduler) handleResult(ctx context.Context, unit *WorkUnit, result WorkResult) {
	s.mu.Lock()
	job, ok := s.jobs[unit.JobID]
	if ok {
		s.pending[unit.JobID]--
	}
	s.mu.Unlock()

	if !ok {
		s.logger.Warn("received result for unknown job", "job_id", unit.JobID)
		return
	}

	// Notify job of completion
	newUnits, err := job.OnComplete(ctx, result)
	if err != nil {
		s.logger.Error("job OnComplete failed", "job_id", unit.JobID, "error", err)
	}

	// Enqueue any new work units
	if len(newUnits) > 0 {
		s.enqueueUnits(unit.JobID, newUnits)
	}

	// Check if job is done
	s.mu.Lock()
	pendingCount := s.pending[unit.JobID]
	isDone := job.Done() && pendingCount == 0
	if isDone {
		delete(s.jobs, unit.JobID)
		delete(s.pending, unit.JobID)
	}
	s.mu.Unlock()

	if isDone {
		s.logger.Info("job completed", "job_id", job.ID(), "type", job.Type())
	}
}

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

// PendingCount returns the number of work units in the queue.
func (s *Scheduler) PendingCount() int {
	return len(s.queue)
}

// ActiveJobs returns the number of active jobs.
func (s *Scheduler) ActiveJobs() int {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return len(s.jobs)
}
