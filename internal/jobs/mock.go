package jobs

import (
	"context"
	"fmt"
	"sync/atomic"
	"time"
)

const MockJobType = "mock"

// MockJob is a simple job for testing the job system.
type MockJob struct {
	Duration   time.Duration
	ShouldFail bool
	steps      atomic.Int32
	totalSteps int32
}

// NewMockJob creates a new mock job with default settings.
func NewMockJob() *MockJob {
	return &MockJob{
		Duration:   100 * time.Millisecond,
		totalSteps: 5,
	}
}

func (j *MockJob) Type() string {
	return MockJobType
}

// Execute runs the mock job.
// It simulates work by sleeping and updating progress.
//
// Note: This implementation is idempotent - it checks current step
// and continues from there rather than starting fresh.
func (j *MockJob) Execute(ctx context.Context) error {
	deps := DepsFromContext(ctx)
	if deps.Logger != nil {
		deps.Logger.Info("mock job executing", "duration", j.Duration, "steps", j.totalSteps)
	}

	stepDuration := j.Duration / time.Duration(j.totalSteps)

	// Resume from current step (idempotent)
	for j.steps.Load() < j.totalSteps {
		select {
		case <-time.After(stepDuration):
			step := j.steps.Add(1)
			if deps.Logger != nil {
				deps.Logger.Debug("mock job progress", "step", step, "total", j.totalSteps)
			}
		case <-ctx.Done():
			return ctx.Err()
		}
	}

	if j.ShouldFail {
		return fmt.Errorf("mock job configured to fail")
	}
	return nil
}

// Status returns the current progress of the mock job.
func (j *MockJob) Status(ctx context.Context) (map[string]string, error) {
	return map[string]string{
		"step":  fmt.Sprintf("%d", j.steps.Load()),
		"total": fmt.Sprintf("%d", j.totalSteps),
	}, nil
}
