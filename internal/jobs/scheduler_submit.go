package jobs

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// Submit starts a job and enqueues its initial work units.
// Creates a persistent record in DefraDB via Manager.
// The job.Start() call runs asynchronously so the HTTP request returns immediately.
func (s *Scheduler) Submit(ctx context.Context, job Job) error {
	// Only store minimal metadata needed for job resumption.
	// Full status is available via job.Status() on the live job.
	metricsFor := job.MetricsFor()
	metadataMap := make(map[string]any)
	if metricsFor != nil && metricsFor.BookID != "" {
		metadataMap["book_id"] = metricsFor.BookID
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

	// Start the job asynchronously - don't block the HTTP request
	// Use a fresh context since the HTTP request context will be cancelled
	go s.startJobAsync(job)

	return nil
}

// startJobAsync runs job.Start() in a background goroutine.
// Uses the scheduler's context instead of the HTTP request context.
func (s *Scheduler) startJobAsync(job Job) {
	// Use scheduler's context (lives for duration of server)
	ctx := s.ctx

	// Inject services into context for the job
	ctx = s.injectServices(ctx)

	units, err := job.Start(ctx)
	if err != nil {
		jobID := job.ID()
		s.logger.Error("job start failed", "job_id", jobID, "error", err)
		s.removeJob(jobID)

		// Mark as failed in DefraDB
		if s.manager != nil && jobID != "" {
			s.manager.UpdateStatus(ctx, jobID, StatusFailed, err.Error())
		}
		return
	}

	s.logger.Info("job started", "job_id", job.ID(), "work_units", len(units))

	// Check if job completed synchronously with no work units (e.g., ingest jobs)
	if len(units) == 0 && job.Done() {
		jobID := job.ID()
		s.logger.Info("job completed synchronously", "id", jobID, "type", job.Type())
		s.removeJob(jobID)

		// Update DefraDB status to completed
		if s.manager != nil {
			if err := s.manager.UpdateStatus(ctx, jobID, StatusCompleted, ""); err != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", err)
			}
		}
		return
	}

	// Enqueue initial work units
	s.enqueueUnits(job.ID(), units)
}

// SubmitByType creates a job from a registered factory and submits it.
// This is used to chain jobs (e.g., process_book triggering finalize_toc).
func (s *Scheduler) SubmitByType(ctx context.Context, jobType string, bookID string) error {
	s.mu.RLock()
	factory, ok := s.factories[jobType]
	s.mu.RUnlock()

	if !ok {
		return fmt.Errorf("no factory registered for job type: %s", jobType)
	}

	// Inject services into context for factory
	enrichedCtx := s.injectServices(ctx)

	// Create metadata for the factory
	metadata := map[string]any{
		"book_id": bookID,
	}

	// Create job from factory
	// The factory signature is: func(ctx, recordID, metadata) (Job, error)
	// For a new job, we pass empty recordID - the factory will load by book_id
	job, err := factory(enrichedCtx, "", metadata)
	if err != nil {
		return fmt.Errorf("failed to create %s job: %w", jobType, err)
	}

	// Submit the job
	return s.Submit(enrichedCtx, job)
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

		// Inject services into context for factory
		enrichedCtx := s.injectServices(ctx)

		// Recreate job from stored metadata
		job, err := factory(enrichedCtx, record.ID, record.Metadata)
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
		units, err := job.Start(enrichedCtx)
		if err != nil {
			s.logger.Error("failed to resume job",
				"job_id", record.ID, "error", err)
			s.manager.UpdateStatus(enrichedCtx, record.ID, StatusFailed, err.Error())
			continue
		}

		// Check if job completed synchronously with no work units
		if len(units) == 0 && job.Done() {
			s.logger.Info("resumed job completed synchronously", "id", record.ID, "type", record.JobType)
			s.removeJob(job.ID())

			if err := s.manager.UpdateStatus(enrichedCtx, record.ID, StatusCompleted, ""); err != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", err)
			}
			resumed++
			continue
		}

		s.enqueueUnits(job.ID(), units)
		resumed++
		s.logger.Info("job resumed", "job_id", record.ID, "type", record.JobType)
	}

	return resumed, nil
}

// injectServices adds services to the context using the registered enricher.
// The enricher is set via SetContextEnricher() after construction.
func (s *Scheduler) injectServices(ctx context.Context) context.Context {
	s.mu.RLock()
	enricher := s.contextEnricher
	s.mu.RUnlock()

	if enricher == nil {
		return ctx
	}

	return enricher(ctx)
}
