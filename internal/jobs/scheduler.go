package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"sync"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/providers"
)

// JobFactory creates a Job instance from stored metadata.
// Used for resuming jobs after restart.
type JobFactory func(id string, metadata map[string]any) (Job, error)

// Scheduler manages workers and distributes work units from jobs.
// It uses Manager to persist job state to DefraDB.
type Scheduler struct {
	mu      sync.RWMutex
	manager *Manager           // For persistence
	workers map[string]*Worker // workers by name
	jobs    map[string]Job     // active jobs by ID
	logger  *slog.Logger

	// Job factories for resumption
	factories map[string]JobFactory

	// Work queue (buffered channel)
	queue chan *WorkUnit

	// Track pending work per job
	pending map[string]int // jobID -> count of pending work units
}

// SchedulerConfig configures a new scheduler.
type SchedulerConfig struct {
	Manager   *Manager // Required for persistence
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
		manager:   cfg.Manager,
		workers:   make(map[string]*Worker),
		jobs:      make(map[string]Job),
		factories: make(map[string]JobFactory),
		pending:   make(map[string]int),
		queue:     make(chan *WorkUnit, queueSize),
		logger:    logger,
	}
}

// RegisterFactory registers a job factory for a job type.
// Required for resuming jobs after restart.
func (s *Scheduler) RegisterFactory(jobType string, factory JobFactory) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.factories[jobType] = factory
	s.logger.Debug("job factory registered", "type", jobType)
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
// Creates a persistent record in DefraDB via Manager.
func (s *Scheduler) Submit(ctx context.Context, job Job) error {
	// Get initial metadata from job status
	metadata, err := job.Status(ctx)
	if err != nil {
		s.logger.Warn("failed to get initial job status", "job_id", job.ID(), "error", err)
	}
	metadataMap := make(map[string]any)
	for k, v := range metadata {
		metadataMap[k] = v
	}

	// Persist to DefraDB if manager available, otherwise generate a temporary ID
	if s.manager != nil {
		recordID, err := s.manager.Create(ctx, job.Type(), metadataMap)
		if err != nil {
			return fmt.Errorf("failed to create job record: %w", err)
		}
		job.SetRecordID(recordID)
		s.logger.Info("job record created", "id", recordID, "type", job.Type())
	} else {
		// Generate a temporary ID for in-memory tracking when no persistence
		job.SetRecordID(uuid.New().String())
	}

	// Track in memory using DefraDB record ID
	s.mu.Lock()
	s.jobs[job.ID()] = job
	s.pending[job.ID()] = 0
	s.mu.Unlock()

	// Update status to running
	if s.manager != nil {
		if err := s.manager.UpdateStatus(ctx, job.ID(), StatusRunning, ""); err != nil {
			s.logger.Warn("failed to update job status", "error", err)
		}
	}

	s.logger.Info("job submitted", "id", job.ID(), "type", job.Type())

	// Start the job to get initial work units
	units, err := job.Start(ctx)
	if err != nil {
		jobID := job.ID()
		s.mu.Lock()
		delete(s.jobs, jobID)
		delete(s.pending, jobID)
		s.mu.Unlock()

		// Mark as failed in DefraDB
		if s.manager != nil && jobID != "" {
			s.manager.UpdateStatus(ctx, jobID, StatusFailed, err.Error())
		}
		return fmt.Errorf("job start failed: %w", err)
	}

	// Enqueue initial work units
	s.enqueueUnits(job.ID(), units)

	return nil
}

// Resume restarts jobs that were interrupted (status: running).
// Requires job factories to be registered for each job type.
func (s *Scheduler) Resume(ctx context.Context) (int, error) {
	if s.manager == nil {
		return 0, fmt.Errorf("manager required for resume")
	}

	// Find interrupted jobs
	records, err := s.manager.List(ctx, ListFilter{Status: StatusRunning})
	if err != nil {
		return 0, fmt.Errorf("failed to list running jobs: %w", err)
	}

	resumed := 0
	for _, record := range records {
		s.mu.RLock()
		factory, ok := s.factories[record.JobType]
		s.mu.RUnlock()

		if !ok {
			s.logger.Warn("no factory for job type, cannot resume",
				"job_id", record.ID, "type", record.JobType)
			continue
		}

		// Recreate job from stored metadata
		job, err := factory(record.ID, record.Metadata)
		if err != nil {
			s.logger.Error("failed to recreate job",
				"job_id", record.ID, "error", err)
			continue
		}

		// Track in memory
		s.mu.Lock()
		s.jobs[job.ID()] = job
		s.pending[job.ID()] = 0
		s.mu.Unlock()

		// Start job (should be idempotent - checks what's already done)
		units, err := job.Start(ctx)
		if err != nil {
			s.logger.Error("failed to resume job",
				"job_id", record.ID, "error", err)
			s.manager.UpdateStatus(ctx, record.ID, StatusFailed, err.Error())
			continue
		}

		s.enqueueUnits(job.ID(), units)
		resumed++
		s.logger.Info("job resumed", "job_id", record.ID, "type", record.JobType)
	}

	return resumed, nil
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
		s.logger.Info("job completed", "id", job.ID(), "type", job.Type())

		// Update DefraDB status
		if s.manager != nil {
			if err := s.manager.UpdateStatus(ctx, job.ID(), StatusCompleted, ""); err != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", err)
			}
		}
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

// WorkerLoad returns rate limiter status for all workers.
func (s *Scheduler) WorkerLoad() map[string]providers.RateLimiterStatus {
	s.mu.RLock()
	defer s.mu.RUnlock()

	load := make(map[string]providers.RateLimiterStatus, len(s.workers))
	for name, w := range s.workers {
		load[name] = w.RateLimiterStatus()
	}
	return load
}

// QueueStats returns queue depth broken down by work unit type.
func (s *Scheduler) QueueStats() QueueStatus {
	s.mu.RLock()
	pendingByJob := make(map[string]int, len(s.pending))
	for k, v := range s.pending {
		pendingByJob[k] = v
	}
	s.mu.RUnlock()

	total := len(s.queue)
	return QueueStatus{
		Total:        total,
		Capacity:     cap(s.queue),
		Utilization:  float64(total) / float64(cap(s.queue)),
		PendingByJob: pendingByJob,
	}
}

// QueueStatus reports current queue state.
type QueueStatus struct {
	Total        int            `json:"total"`
	Capacity     int            `json:"capacity"`
	Utilization  float64        `json:"utilization"`
	PendingByJob map[string]int `json:"pending_by_job"`
}
