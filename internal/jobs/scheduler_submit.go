package jobs

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

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
