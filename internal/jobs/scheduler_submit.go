package jobs

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"sort"
	"time"

	"github.com/google/uuid"
)

var (
	resumeRetryInitialBackoff = time.Second
	resumeRetryMaxBackoff     = 30 * time.Second
)

type resumeAttempt struct {
	job   Job
	units []WorkUnit
}

// retryTransientOperation retries only infrastructure-class errors. Deterministic
// factory/config/content errors still return immediately and become actionable
// terminal failures; transient DefraDB/network errors wait without mutating the
// durable running record.
func retryTransientOperation[T any](ctx context.Context, logger *slog.Logger, operation, jobID string, fn func() (T, error)) (T, error) {
	var zero T
	backoff := resumeRetryInitialBackoff
	for attempt := 1; ; attempt++ {
		value, err := fn()
		if err == nil {
			return value, nil
		}
		if !IsRetriableError(err) {
			return zero, err
		}

		logger.Warn("transient job operation failed; retrying",
			"job_id", jobID,
			"operation", operation,
			"attempt", attempt,
			"retry_in", backoff,
			"error", err)

		timer := time.NewTimer(backoff)
		select {
		case <-ctx.Done():
			if !timer.Stop() {
				<-timer.C
			}
			return zero, ctx.Err()
		case <-timer.C:
		}
		backoff *= 2
		if backoff > resumeRetryMaxBackoff {
			backoff = resumeRetryMaxBackoff
		}
	}
}

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

	record := NewRecord(job.Type(), metadataMap)
	bookSeq := record.CreatedAt.UnixNano()

	// Persist to DefraDB if manager available, otherwise generate a temporary ID
	if s.manager != nil {
		recordID, err := s.manager.CreateRecord(ctx, record)
		if err != nil {
			return fmt.Errorf("failed to create job record: %w", err)
		}
		job.SetRecordID(recordID)
		s.logger.Debug("job record created", "id", recordID, "type", job.Type())
	} else {
		// Generate a temporary ID for in-memory tracking when no persistence
		job.SetRecordID(uuid.New().String())
		bookSeq = time.Now().UTC().UnixNano()
	}

	// Track in memory using DefraDB record ID
	startedAt := time.Now().UTC()
	s.mu.Lock()
	s.jobs[job.ID()] = job
	s.jobSeq[job.ID()] = bookSeq
	s.pending[job.ID()] = 0
	s.lastProgress[job.ID()] = startedAt
	s.mu.Unlock()

	// Update status to running
	if s.manager != nil {
		if err := s.manager.UpdateStatus(ctx, job.ID(), StatusRunning, ""); err != nil {
			s.logger.Warn("failed to update job status", "error", err)
		}
		if err := s.manager.UpdateHeartbeat(ctx, job.ID(), startedAt, startedAt); err != nil {
			s.logger.Warn("failed to persist initial job heartbeat", "job_id", job.ID(), "error", err)
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
	ctx := s.schedulerContext()

	// Inject services into context for the job
	ctx = s.injectServices(ctx)

	units, err := retryTransientOperation(ctx, s.logger, "start job", job.ID(), func() ([]WorkUnit, error) {
		return s.safeJobStart(ctx, job)
	})
	if err != nil {
		jobID := job.ID()
		// Shutdown is an interruption, not a book failure. Leave the durable record
		// running so startup resume reconstructs it on the next server process.
		if ctx.Err() != nil {
			s.logger.Info("job start interrupted by scheduler shutdown", "job_id", jobID, "error", err)
			s.removeJob(jobID)
			return
		}
		s.logger.Error("job start failed", "job_id", jobID, "error", err)
		s.failBookForJob(ctx, job, err.Error())
		s.removeJob(jobID)

		// Mark as failed in DefraDB
		if s.manager != nil && jobID != "" {
			s.manager.UpdateStatus(ctx, jobID, StatusFailed, err.Error())
		}
		return
	}

	s.logger.Debug("job started", "job_id", job.ID(), "work_units", len(units))

	// Check if job completed synchronously with no work units (e.g., ingest jobs)
	if len(units) == 0 && job.Done() {
		jobID := job.ID()
		s.logger.Debug("job completed synchronously", "id", jobID, "type", job.Type())
		s.removeJob(jobID)

		// Update DefraDB status to completed
		if s.manager != nil {
			if err := s.manager.UpdateStatus(ctx, jobID, StatusCompleted, ""); err != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", err)
			}
		}
		return
	}
	if len(units) == 0 {
		jobID := job.ID()
		reason := noWorkFailureReason(job, "job started with no work units and is not done")
		err := fmt.Errorf("%s", reason)
		s.logger.Error("job start produced no work", "job_id", jobID, "type", job.Type())
		s.failBookForJob(ctx, job, err.Error())
		s.removeJob(jobID)
		if s.manager != nil && jobID != "" {
			if updateErr := s.manager.UpdateStatus(ctx, jobID, StatusFailed, err.Error()); updateErr != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", updateErr)
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

	// Find interrupted jobs. The list operation itself is retried so a DefraDB
	// warm-up or restart cannot make the one startup resume pass disappear.
	records, err := retryTransientOperation(ctx, s.logger, "list running jobs", "", func() ([]*Record, error) {
		return s.manager.List(ctx, ListFilter{Status: StatusRunning, Limit: 10000})
	})
	if err != nil {
		return 0, fmt.Errorf("failed to list running jobs: %w", err)
	}
	waiting, err := retryTransientOperation(ctx, s.logger, "list waiting-provider jobs", "", func() ([]*Record, error) {
		return s.manager.List(ctx, ListFilter{Status: StatusWaitingProvider, Limit: 10000})
	})
	if err != nil {
		return 0, fmt.Errorf("failed to list waiting-provider jobs: %w", err)
	}
	records = append(records, waiting...)
	records = s.dedupeRunningRecords(ctx, records)

	resumed := 0
	for _, record := range records {
		s.mu.RLock()
		factory, ok := s.factories[record.JobType]
		s.mu.RUnlock()

		if !ok {
			s.logger.Warn("no factory for job type, cannot resume",
				"job_id", record.ID, "type", record.JobType)
			s.failBookByRecord(ctx, record, "resume failed: no factory registered for job type "+record.JobType)
			continue
		}

		// If a caller invokes Resume more than once, never recreate an already live
		// record. This also makes an operational resume kick safe.
		s.mu.RLock()
		_, alreadyActive := s.jobs[record.ID]
		s.mu.RUnlock()
		if alreadyActive {
			continue
		}

		// Inject services into context for factory
		enrichedCtx := s.injectServices(ctx)

		// Recreate and start as one retryable operation. A fresh job is loaded on
		// every attempt so partial in-memory state from a timed-out Start is never
		// reused. Durable page/book state remains the source of truth.
		var lastJob Job
		attempt, err := retryTransientOperation(enrichedCtx, s.logger, "recreate and start job", record.ID, func() (resumeAttempt, error) {
			job, factoryErr := factory(enrichedCtx, record.ID, record.Metadata)
			if factoryErr != nil {
				return resumeAttempt{}, factoryErr
			}
			lastJob = job
			units, startErr := s.safeJobStart(enrichedCtx, job)
			if startErr != nil {
				return resumeAttempt{}, startErr
			}
			return resumeAttempt{job: job, units: units}, nil
		})
		if err != nil {
			if errors.Is(err, context.Canceled) || (errors.Is(err, context.DeadlineExceeded) && enrichedCtx.Err() != nil) {
				return resumed, err
			}
			s.logger.Error("failed to recreate or start job",
				"job_id", record.ID, "error", err)
			if lastJob != nil {
				s.failBookForJob(enrichedCtx, lastJob, "resume failed: "+err.Error())
				if updateErr := s.manager.UpdateStatus(enrichedCtx, record.ID, StatusFailed, err.Error()); updateErr != nil {
					s.logger.Warn("failed to update job status in DefraDB", "job_id", record.ID, "error", updateErr)
				}
			} else {
				s.failBookByRecord(enrichedCtx, record, "resume failed to recreate job: "+err.Error())
			}
			continue
		}
		job, units := attempt.job, attempt.units

		// Track in memory. Guard a zero CreatedAt (e.g. a record whose created_at
		// failed to parse on load): its UnixNano() is a large negative that would
		// sort BEFORE every real book; map it to the 0 = unset sentinel instead.
		seq := record.CreatedAt.UnixNano()
		if record.CreatedAt.IsZero() {
			seq = 0
		}
		s.mu.Lock()
		s.jobs[job.ID()] = job
		s.jobSeq[job.ID()] = seq
		s.pending[job.ID()] = 0
		if record.LastProgressAt != nil {
			s.lastProgress[job.ID()] = *record.LastProgressAt
		}
		s.mu.Unlock()

		if err := s.manager.UpdateRuntimeStatus(enrichedCtx, record.ID, StatusRunning, ""); err != nil {
			s.logger.Warn("failed to persist resumed running state", "job_id", record.ID, "error", err)
		}

		// Check if job completed synchronously with no work units
		if len(units) == 0 && job.Done() {
			s.logger.Debug("resumed job completed synchronously", "id", record.ID, "type", record.JobType)
			s.removeJob(job.ID())

			if err := s.manager.UpdateStatus(enrichedCtx, record.ID, StatusCompleted, ""); err != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", err)
			}
			resumed++
			continue
		}
		if len(units) == 0 {
			reason := noWorkFailureReason(job, "resumed job produced no work units and is not done")
			err := fmt.Errorf("%s", reason)
			s.logger.Error("failed to resume job",
				"job_id", record.ID,
				"type", record.JobType,
				"error", err)
			s.failBookForJob(enrichedCtx, job, err.Error())
			s.removeJob(job.ID())
			if updateErr := s.manager.UpdateStatus(enrichedCtx, record.ID, StatusFailed, err.Error()); updateErr != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", updateErr)
			}
			continue
		}

		s.enqueueUnits(job.ID(), units)
		resumed++
		s.logger.Debug("job resumed", "job_id", record.ID, "type", record.JobType)
	}

	return resumed, nil
}

func (s *Scheduler) dedupeRunningRecords(ctx context.Context, records []*Record) []*Record {
	sort.SliceStable(records, func(i, j int) bool {
		left, right := records[i].CreatedAt, records[j].CreatedAt
		if left.IsZero() && right.IsZero() {
			return records[i].ID > records[j].ID
		}
		if left.IsZero() {
			return false
		}
		if right.IsZero() {
			return true
		}
		if left.Equal(right) {
			return records[i].ID > records[j].ID
		}
		return left.After(right)
	})

	seen := make(map[string]*Record)
	kept := make([]*Record, 0, len(records))
	for _, record := range records {
		if record == nil {
			continue
		}
		if record.BookID == "" {
			kept = append(kept, record)
			continue
		}
		key := record.JobType + "\x00" + record.BookID
		if first := seen[key]; first != nil {
			msg := fmt.Sprintf("duplicate running %s job for book %s cancelled during resume; keeping %s", record.JobType, record.BookID, first.ID)
			if err := s.manager.UpdateStatus(ctx, record.ID, StatusCancelled, msg); err != nil {
				s.logger.Warn("failed to cancel duplicate running job",
					"job_id", record.ID,
					"kept_job_id", first.ID,
					"type", record.JobType,
					"book_id", record.BookID,
					"error", err)
			} else {
				s.logger.Warn("cancelled duplicate running job during resume",
					"job_id", record.ID,
					"kept_job_id", first.ID,
					"type", record.JobType,
					"book_id", record.BookID)
			}
			continue
		}
		seen[key] = record
		kept = append(kept, record)
	}
	return kept
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
