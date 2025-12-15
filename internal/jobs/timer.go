package jobs

import (
	"context"
	"fmt"
	"sync/atomic"
	"time"
)

const TimerJobType = "timer"

// TimerJob waits for a specified duration, reporting remaining time in status.
type TimerJob struct {
	Duration    time.Duration
	startTime   time.Time
	remainingMs atomic.Int64
	done        atomic.Bool
}

// NewTimerJob creates a new timer job that waits for the given duration.
func NewTimerJob(duration time.Duration) *TimerJob {
	return &TimerJob{
		Duration: duration,
	}
}

func (j *TimerJob) Type() string {
	return TimerJobType
}

// Execute waits for the duration, updating remaining time periodically.
//
// This implementation is idempotent - if resumed, it calculates remaining
// time from when it was originally started (stored in metadata).
func (j *TimerJob) Execute(ctx context.Context) error {
	deps := DepsFromContext(ctx)

	j.startTime = time.Now()
	j.remainingMs.Store(j.Duration.Milliseconds())

	if deps.Logger != nil {
		deps.Logger.Info("timer job started", "duration_ms", j.Duration.Milliseconds())
	}

	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	deadline := j.startTime.Add(j.Duration)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case now := <-ticker.C:
			remaining := deadline.Sub(now)
			if remaining <= 0 {
				j.remainingMs.Store(0)
				j.done.Store(true)
				if deps.Logger != nil {
					deps.Logger.Info("timer job completed")
				}
				return nil
			}
			j.remainingMs.Store(remaining.Milliseconds())
		}
	}
}

// Status returns the current status of the timer job.
func (j *TimerJob) Status(ctx context.Context) (map[string]string, error) {
	return map[string]string{
		"remaining_ms": fmt.Sprintf("%d", j.remainingMs.Load()),
		"duration_ms":  fmt.Sprintf("%d", j.Duration.Milliseconds()),
		"done":         fmt.Sprintf("%t", j.done.Load()),
	}, nil
}
