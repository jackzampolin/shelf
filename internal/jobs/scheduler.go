package jobs

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"runtime/debug"
	"sync"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// cpuRequeueBackoff is the delay between resubmit attempts for a unit bounced
// by a full pool queue.
const cpuRequeueBackoff = 250 * time.Millisecond

// heartbeatInterval bounds how stale a healthy active job can look in durable
// state. Progress timestamps are updated in memory per result and flushed on
// this cadence to avoid a DefraDB write for every OCR page.
const heartbeatInterval = 30 * time.Second

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
	jobSeq  map[string]int64      // jobID -> created_at unix nanos for book-aware priority
	logger  *slog.Logger

	// Job factories for resumption
	factories map[string]JobFactory

	// Results channel - all pools send results here
	results chan workerResult

	// Requeue buffer for units bounced by a full pool queue (backpressure).
	requeue chan *WorkUnit

	// Track pending work per job
	pending map[string]int // jobID -> count of pending work units

	// Durable liveness bookkeeping. lastProgress is updated only when a work
	// result arrives; the heartbeat loop persists it alongside its own timestamp.
	lastProgress map[string]time.Time

	// Providers currently blocking each job. A job remains waiting_provider
	// until every provider that parked it reports recovery.
	waitingProviders map[string]map[string]struct{}

	// Running state
	running bool
	ctx     context.Context // Scheduler's long-lived context (set in Start)

	// Debug counters
	receivedCPU int
	receivedOCR int
	receivedLLM int
	receivedTTS int

	// Sink for fire-and-forget metrics writes (passed to pools)
	sink *defra.Sink

	// Context enricher for async job context injection
	contextEnricher func(context.Context) context.Context
}

// schedulerContext returns the scheduler's long-lived context in a race-free way.
// Falls back to context.Background() if Start hasn't been called yet.
func (s *Scheduler) schedulerContext() context.Context {
	s.mu.RLock()
	ctx := s.ctx
	s.mu.RUnlock()
	if ctx == nil {
		return context.Background()
	}
	return ctx
}

// requeueLoop drains the requeue buffer, retrying each parked unit until the
// pool accepts it or the context is cancelled. A single drainer is sufficient:
// only CPU-pool units ever hit ErrWorkerQueueFull (provider pools use an
// unbounded queue), and they all share one CPU queue — so if the head unit is
// blocked on a full queue, every other parked unit would be too. Head-of-line
// waiting is therefore bounded to one backoff interval, not a starvation risk.
func (s *Scheduler) requeueLoop(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case unit := <-s.requeue:
			s.resubmitWithBackoff(ctx, unit)
		}
	}
}

func (s *Scheduler) resubmitWithBackoff(ctx context.Context, unit *WorkUnit) {
	if !s.jobActive(unit.JobID) {
		return
	}
	pool := s.findPool(unit)
	if pool == nil {
		s.emitFailure(unit, fmt.Errorf("no pool available for type %s provider %s", unit.Type, unit.Provider))
		return
	}

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		if !s.jobActive(unit.JobID) {
			return
		}

		err := pool.Submit(unit)
		if err == nil {
			return
		}
		if !errors.Is(err, ErrWorkerQueueFull) {
			s.emitFailure(unit, err)
			return
		}

		select {
		case <-ctx.Done():
			return
		case <-time.After(cpuRequeueBackoff):
		}
	}
}

func (s *Scheduler) jobActive(jobID string) bool {
	s.mu.RLock()
	defer s.mu.RUnlock()
	_, ok := s.jobs[jobID]
	return ok
}

// emitFailure sends a failed WorkResult for a unit that could not be routed.
// The send is non-blocking: emitFailure is reachable from the results-consumer
// goroutine (handleResult -> OnComplete -> enqueueUnits), so a blocking send on
// a full s.results buffer would deadlock the only drainer. On overflow the send
// is offloaded to a short-lived goroutine, keeping s.pending accounting correct
// (the result still lands and is handled) without stalling the consumer.
func (s *Scheduler) emitFailure(unit *WorkUnit, err error) {
	wr := workerResult{
		JobID: unit.JobID,
		Unit:  unit,
		Result: WorkResult{
			WorkUnitID: unit.ID,
			Success:    false,
			Error:      err,
		},
	}
	select {
	case s.results <- wr:
	default:
		go func() { s.results <- wr }()
	}
}

// safeJobStart runs job.Start with panic recovery, converting a panic into an
// error so one bad job fails only its own book instead of crashing the server.
func (s *Scheduler) safeJobStart(ctx context.Context, job Job) (units []WorkUnit, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("panic in job.Start: %v", r)
			s.logger.Error("recovered panic in job.Start",
				"job_id", job.ID(), "panic", r, "stack", string(debug.Stack()))
		}
	}()
	return job.Start(ctx)
}

// safeJobOnComplete runs job.OnComplete with panic recovery, converting a panic
// into an error so the failure path marks the book failed instead of crashing.
func (s *Scheduler) safeJobOnComplete(ctx context.Context, job Job, result WorkResult) (units []WorkUnit, err error) {
	defer func() {
		if r := recover(); r != nil {
			err = fmt.Errorf("panic in job.OnComplete: %v", r)
			s.logger.Error("recovered panic in job.OnComplete",
				"job_id", job.ID(), "panic", r, "stack", string(debug.Stack()))
		}
	}()
	return job.OnComplete(ctx, result)
}

// failBookForJob marks a job's book terminally failed if the job supports it.
func (s *Scheduler) failBookForJob(ctx context.Context, job Job, reason string) {
	if bf, ok := job.(BookFailer); ok {
		bf.FailBook(ctx, reason)
	}
}

func noWorkFailureReason(job Job, fallback string) string {
	if provider, ok := job.(NoWorkFailureProvider); ok {
		if detail := provider.NoWorkFailure(); detail != "" {
			return detail
		}
	}
	return fallback
}

// failBookByRecord marks a book failed when no live Job exists (e.g. a Resume
// factory failure). It also marks the job record failed so the stale "running"
// record does not defeat the reconciler. The "failed" status string must match
// process_book/job.BookStatusFailed.
func (s *Scheduler) failBookByRecord(ctx context.Context, record *Record, reason string) {
	if record == nil {
		return
	}
	if s.manager != nil && record.ID != "" {
		if err := s.manager.UpdateStatus(ctx, record.ID, StatusFailed, reason); err != nil {
			s.logger.Warn("failed to mark job record failed", "job_id", record.ID, "error", err)
		}
	}
	if record.BookID == "" || s.manager == nil || s.manager.defra == nil {
		return
	}
	// Don't stomp the book status if another job is actively processing it: a
	// live in-memory job, or a different queued/running record for the same book.
	if s.GetJobByBookID(record.BookID) != nil {
		s.logger.Debug("skipping book-fail write; an active job owns the book",
			"book_id", record.BookID, "record_id", record.ID)
		return
	}
	if recs, err := s.manager.List(ctx, ListFilter{BookID: record.BookID}); err == nil {
		for _, r := range recs {
			if r.ID == record.ID {
				continue
			}
			if r.Status == StatusRunning || r.Status == StatusQueued || r.Status == StatusWaitingProvider {
				s.logger.Debug("skipping book-fail write; another live job record for the book",
					"book_id", record.BookID, "other_record_id", r.ID)
				return
			}
		}
	}
	if err := s.manager.defra.Update(ctx, "Book", record.BookID, map[string]any{
		"status":        "failed",
		"status_reason": reason,
	}); err != nil {
		s.logger.Warn("failed to mark book failed by record", "book_id", record.BookID, "error", err)
	}
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

	results := make(chan workerResult, 1000) // Buffered results channel
	logger.Debug("scheduler created")

	return &Scheduler{
		manager:          cfg.Manager,
		pools:            make(map[string]WorkerPool),
		jobs:             make(map[string]Job),
		jobSeq:           make(map[string]int64),
		factories:        make(map[string]JobFactory),
		pending:          make(map[string]int),
		lastProgress:     make(map[string]time.Time),
		waitingProviders: make(map[string]map[string]struct{}),
		results:          results,
		requeue:          make(chan *WorkUnit, 100000),
		logger:           logger,
		sink:             cfg.Sink,
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
	delete(s.jobSeq, jobID)
	delete(s.pending, jobID)
	delete(s.lastProgress, jobID)
	delete(s.waitingProviders, jobID)
	s.mu.Unlock()
}

// GetJobByBookID returns an active job processing the given book, if any.
// Returns nil if no active job is found for this book.
func (s *Scheduler) GetJobByBookID(bookID string) Job {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, job := range s.jobs {
		if provider, ok := job.(BookIDProvider); ok {
			if provider.BookID() == bookID {
				return job
			}
		}
	}
	return nil
}

// GetJobByBookIDAndType returns an active job of the given type for a book, if any.
// Returns nil if no active matching job is found.
func (s *Scheduler) GetJobByBookIDAndType(bookID, jobType string) Job {
	s.mu.RLock()
	defer s.mu.RUnlock()

	for _, job := range s.jobs {
		if job.Type() != jobType {
			continue
		}
		if provider, ok := job.(BookIDProvider); ok && provider.BookID() == bookID {
			return job
		}
	}
	return nil
}

// CancelActiveJobsByBookIDAndType removes active matching jobs from scheduler
// state and marks their persistent records cancelled.
func (s *Scheduler) CancelActiveJobsByBookIDAndType(ctx context.Context, bookID, jobType, reason string) int {
	var jobIDs []string

	s.mu.Lock()
	for jobID, job := range s.jobs {
		if job.Type() != jobType {
			continue
		}
		if provider, ok := job.(BookIDProvider); ok && provider.BookID() == bookID {
			delete(s.jobs, jobID)
			delete(s.jobSeq, jobID)
			delete(s.pending, jobID)
			delete(s.lastProgress, jobID)
			delete(s.waitingProviders, jobID)
			jobIDs = append(jobIDs, jobID)
		}
	}
	s.mu.Unlock()

	for _, jobID := range jobIDs {
		purged := 0
		s.mu.RLock()
		pools := make([]WorkerPool, 0, len(s.pools))
		for _, pool := range s.pools {
			pools = append(pools, pool)
		}
		s.mu.RUnlock()
		for _, pool := range pools {
			if canceller, ok := pool.(JobWorkCanceller); ok {
				purged += canceller.CancelJob(jobID)
			}
		}
		s.logger.Warn("cancelled active job",
			"job_id", jobID,
			"type", jobType,
			"book_id", bookID,
			"reason", reason,
			"purged_units", purged)
		if s.manager != nil {
			if err := s.manager.UpdateStatus(ctx, jobID, StatusCancelled, reason); err != nil {
				s.logger.Warn("failed to mark active job cancelled",
					"job_id", jobID,
					"type", jobType,
					"book_id", bookID,
					"error", err)
			}
		}
	}

	return len(jobIDs)
}

// Start begins the scheduler and all registered pools.
// Blocks until context is cancelled.
func (s *Scheduler) Start(ctx context.Context) {
	s.logger.Debug("scheduler start called")

	s.mu.Lock()
	if s.running {
		s.logger.Warn("scheduler Start called but already running")
		s.mu.Unlock()
		return
	}
	s.running = true
	s.ctx = ctx // Store for async job operations

	// Start all pools
	for name, p := range s.pools {
		s.logger.Debug("starting pool from scheduler", "name", name, "type", p.Type())
		go p.Start(ctx)
	}
	s.mu.Unlock()

	// Periodically catch books stranded in "processing" (flag-only).
	go s.reconcileLoop(ctx)
	go s.requeueLoop(ctx)
	go s.heartbeatLoop(ctx)

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
			bufferLen := len(s.results)
			hasOCRData := wr.Result.OCRResult != nil
			hasCPUData := wr.Result.CPUResult != nil
			hasChatData := wr.Result.ChatResult != nil

			// Track received unit distribution for debugging.
			switch wr.Unit.Type {
			case WorkUnitTypeCPU:
				s.receivedCPU++
			case WorkUnitTypeOCR:
				s.receivedOCR++
				s.logger.Debug("received OCR result",
					"unit_id", wr.Unit.ID,
					"has_ocr_result", hasOCRData,
				)
			case WorkUnitTypeLLM:
				s.receivedLLM++
			case WorkUnitTypeTTS:
				s.receivedTTS++
			default:
				s.logger.Warn("scheduler received unknown unit type",
					"unit_type", wr.Unit.Type,
					"unit_id", wr.Unit.ID)
			}

			s.logger.Debug("scheduler received result",
				"job_id", wr.JobID,
				"unit_id", wr.Unit.ID,
				"unit_type", wr.Unit.Type,
				"success", wr.Result.Success,
				"has_ocr_data", hasOCRData,
				"has_cpu_data", hasCPUData,
				"has_chat_data", hasChatData,
				"buffer_len", bufferLen,
				"received_cpu", s.receivedCPU,
				"received_ocr", s.receivedOCR,
				"received_llm", s.receivedLLM,
				"received_tts", s.receivedTTS,
			)
			handleStart := time.Now()
			s.handleResult(ctx, wr)
			s.logger.Debug("handleResult completed", "duration_ms", time.Since(handleStart).Milliseconds())
		}
	}
}

// handleResult processes a work result and notifies the job.
func (s *Scheduler) handleResult(ctx context.Context, wr workerResult) {
	s.mu.Lock()
	job, ok := s.jobs[wr.JobID]
	if ok {
		s.pending[wr.JobID]--
		s.lastProgress[wr.JobID] = time.Now().UTC()
	}
	s.mu.Unlock()

	if !ok {
		s.logger.Warn("received result for unknown job", "job_id", wr.JobID)
		return
	}

	// Inject services into context for job handlers
	enrichedCtx := s.injectServices(ctx)

	// Notify job of completion (panic-safe: a panic becomes an error that marks
	// the book failed rather than crashing the scheduler).
	newUnits, err := s.safeJobOnComplete(enrichedCtx, job, wr.Result)
	if err != nil {
		s.logger.Error("job OnComplete failed", "job_id", wr.JobID, "error", err)
		s.failBookForJob(enrichedCtx, job, err.Error())
		s.removeJob(wr.JobID)
		if s.manager != nil {
			if updateErr := s.manager.UpdateStatus(ctx, wr.JobID, StatusFailed, err.Error()); updateErr != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", updateErr)
			}
		}
		return
	}

	// Enqueue any new work units
	if len(newUnits) > 0 {
		s.enqueueUnits(wr.JobID, newUnits)
	}

	// Check if job is done. A multi-phase job is not allowed to drain its final
	// unit while remaining nonterminal: without this invariant it stays
	// "running" forever with pending_units=0 and no event capable of waking it.
	s.mu.Lock()
	pendingCount := s.pending[wr.JobID]
	jobDone := job.Done()
	isDone := jobDone && pendingCount == 0
	isDrainedNonterminal := !jobDone && pendingCount == 0
	if isDone || isDrainedNonterminal {
		delete(s.jobs, wr.JobID)
		delete(s.jobSeq, wr.JobID)
		delete(s.pending, wr.JobID)
		delete(s.lastProgress, wr.JobID)
		delete(s.waitingProviders, wr.JobID)
	}
	s.mu.Unlock()

	if isDrainedNonterminal {
		reason := noWorkFailureReason(job, "job drained all work units but is not done")
		s.logger.Error("job drained without reaching a terminal state",
			"job_id", wr.JobID,
			"job_type", job.Type(),
			"reason", reason)
		s.failBookForJob(enrichedCtx, job, reason)
		if s.manager != nil {
			if updateErr := s.manager.UpdateStatus(ctx, wr.JobID, StatusFailed, reason); updateErr != nil {
				s.logger.Warn("failed to update drained job status in DefraDB", "error", updateErr)
			}
		}
		return
	}

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
