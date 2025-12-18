package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"runtime"
	"sync"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/providers"
)

// JobFactory creates a Job instance from stored metadata.
// Used for resuming jobs after restart.
type JobFactory func(id string, metadata map[string]any) (Job, error)

// Scheduler manages workers and distributes work units from jobs.
// Each worker runs as its own goroutine with its own queue.
// The scheduler routes work units to appropriate workers and handles results.
type Scheduler struct {
	mu      sync.RWMutex
	manager *Manager                    // For persistence
	workers map[string]WorkerInterface  // all workers by name
	jobs    map[string]Job              // active jobs by ID
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

	// Metrics recorder (passed to workers for automatic metrics recording)
	metricsRecorder *metrics.Recorder
}

// SchedulerConfig configures a new scheduler.
type SchedulerConfig struct {
	Manager         *Manager          // Required for persistence
	Logger          *slog.Logger
	MetricsRecorder *metrics.Recorder // Optional - enables automatic metrics recording
}

// NewScheduler creates a new scheduler.
func NewScheduler(cfg SchedulerConfig) *Scheduler {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	return &Scheduler{
		manager:         cfg.Manager,
		workers:         make(map[string]WorkerInterface),
		cpuWorkers:      make([]*CPUWorker, 0),
		jobs:            make(map[string]Job),
		factories:       make(map[string]JobFactory),
		pending:         make(map[string]int),
		results:         make(chan workerResult, 1000), // Buffered results channel
		logger:          logger,
		metricsRecorder: cfg.MetricsRecorder,
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
// Must be called before Start.
func (s *Scheduler) RegisterWorker(w WorkerInterface) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Initialize worker with shared results channel
	w.init(s.results)

	s.workers[w.Name()] = w
	s.logger.Info("worker registered", "name", w.Name(), "type", w.Type())
}

// InitFromRegistry creates workers from all providers in the registry.
// This is the recommended way to set up workers - one provider = one worker.
// Each worker pulls its rate limit from the provider's configured value.
func (s *Scheduler) InitFromRegistry(registry *providers.Registry) error {
	// Create workers from LLM clients
	for name, client := range registry.LLMClients() {
		worker, err := NewWorker(WorkerConfig{
			Name:            name,
			LLMClient:       client,
			Logger:          s.logger,
			MetricsRecorder: s.metricsRecorder,
			// RPS pulled from client.RequestsPerSecond() by NewWorker
		})
		if err != nil {
			return fmt.Errorf("failed to create LLM worker %s: %w", name, err)
		}
		s.RegisterWorker(worker)
	}

	// Create workers from OCR providers
	for name, provider := range registry.OCRProviders() {
		worker, err := NewWorker(WorkerConfig{
			Name:            name,
			OCRProvider:     provider,
			Logger:          s.logger,
			MetricsRecorder: s.metricsRecorder,
			// RPS pulled from provider.RequestsPerSecond() by NewWorker
		})
		if err != nil {
			return fmt.Errorf("failed to create OCR worker %s: %w", name, err)
		}
		s.RegisterWorker(worker)
	}

	s.logger.Info("initialized workers from registry",
		"llm_workers", len(registry.LLMClients()),
		"ocr_workers", len(registry.OCRProviders()),
	)

	return nil
}

// InitCPUWorkers creates n CPU workers for CPU-bound tasks.
// If n <= 0, uses runtime.NumCPU().
// Returns the created workers so callers can register task handlers.
func (s *Scheduler) InitCPUWorkers(n int) []*CPUWorker {
	if n <= 0 {
		n = runtime.NumCPU()
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	workers := make([]*CPUWorker, n)
	for i := 0; i < n; i++ {
		w := NewCPUWorker(CPUWorkerConfig{
			Name:   fmt.Sprintf("cpu-%d", i),
			Logger: s.logger,
		})
		w.init(s.results)
		workers[i] = w
		s.workers[w.Name()] = w
	}
	s.cpuWorkers = workers

	s.logger.Info("initialized CPU workers", "count", n)
	return workers
}

// RegisterCPUHandler registers a task handler on all CPU workers.
// Convenience method - equivalent to calling RegisterHandler on each worker.
func (s *Scheduler) RegisterCPUHandler(taskName string, handler CPUTaskHandler) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, w := range s.cpuWorkers {
		w.RegisterHandler(taskName, handler)
	}
	s.logger.Debug("registered CPU handler on all workers", "task", taskName, "workers", len(s.cpuWorkers))
}

// GetWorker returns a worker by name.
func (s *Scheduler) GetWorker(name string) (WorkerInterface, bool) {
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
		return 0, ErrManagerRequired
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

// enqueueUnits routes work units to the appropriate worker queues.
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

		worker := s.findWorker(unit)
		if worker == nil {
			s.logger.Error("no worker found for work unit",
				"unit_id", unit.ID,
				"type", unit.Type,
				"provider", unit.Provider,
			)
			// Send failure result
			s.results <- workerResult{
				JobID: jobID,
				Unit:  unit,
				Result: WorkResult{
					WorkUnitID: unit.ID,
					Success:    false,
					Error:      fmt.Errorf("no worker available for type %s provider %s", unit.Type, unit.Provider),
				},
			}
			continue
		}

		if err := worker.Submit(unit); err != nil {
			s.logger.Warn("failed to submit to worker", "worker", worker.Name(), "error", err)
			// Send failure result
			s.results <- workerResult{
				JobID: jobID,
				Unit:  unit,
				Result: WorkResult{
					WorkUnitID: unit.ID,
					Success:    false,
					Error:      err,
				},
			}
		}
	}

	s.logger.Debug("enqueued work units", "job_id", jobID, "count", len(units))
}

// findWorker finds an appropriate worker for the work unit.
func (s *Scheduler) findWorker(unit *WorkUnit) WorkerInterface {
	s.mu.Lock()
	defer s.mu.Unlock()

	// CPU work units use round-robin across CPU workers
	if unit.Type == WorkUnitTypeCPU {
		if len(s.cpuWorkers) == 0 {
			return nil
		}
		// Round-robin selection
		w := s.cpuWorkers[s.cpuIndex]
		s.cpuIndex = (s.cpuIndex + 1) % len(s.cpuWorkers)
		return w
	}

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
		if rw, ok := w.(*Worker); ok {
			rlStatus := rw.RateLimiterStatus()
			info.RateLimiter = &rlStatus
		}
		status[name] = info
	}
	return status
}

// WorkerStatusInfo reports a worker's current state.
type WorkerStatusInfo struct {
	Type        string                      `json:"type"`
	QueueDepth  int                         `json:"queue_depth"`
	RateLimiter *providers.RateLimiterStatus `json:"rate_limiter,omitempty"`
}
