package jobs

import (
	"context"
	"fmt"
	"sync/atomic"

	"github.com/jackzampolin/shelf/internal/providers"
)

// CountingJob is a simple job that counts work unit completions.
// Useful for testing the scheduler.
type CountingJob struct {
	id        string // DefraDB record ID (set by scheduler after persistence)
	total     int
	completed atomic.Int32
	done      atomic.Bool
}

func NewCountingJob(total int) *CountingJob {
	return &CountingJob{
		total: total,
	}
}

// ID returns the DefraDB record ID. Empty until persisted.
func (j *CountingJob) ID() string {
	return j.id
}

// SetRecordID sets the DefraDB record ID after persistence.
func (j *CountingJob) SetRecordID(id string) {
	j.id = id
}

func (j *CountingJob) Type() string { return "counting" }

func (j *CountingJob) Start(ctx context.Context) ([]WorkUnit, error) {
	jobID := j.ID()
	units := make([]WorkUnit, j.total)
	for i := 0; i < j.total; i++ {
		units[i] = WorkUnit{
			ID:   fmt.Sprintf("%s-unit-%d", jobID, i),
			Type: WorkUnitTypeLLM,
			ChatRequest: &providers.ChatRequest{
				Messages: []providers.Message{
					{Role: "user", Content: "test"},
				},
			},
		}
	}
	return units, nil
}

func (j *CountingJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
	j.completed.Add(1)
	if int(j.completed.Load()) >= j.total {
		j.done.Store(true)
	}
	return nil, nil
}

func (j *CountingJob) Done() bool {
	return j.done.Load()
}

func (j *CountingJob) Status(ctx context.Context) (map[string]string, error) {
	return map[string]string{
		"completed": fmt.Sprintf("%d", j.completed.Load()),
		"total":     fmt.Sprintf("%d", j.total),
	}, nil
}

func (j *CountingJob) Completed() int {
	return int(j.completed.Load())
}

// Progress returns per-provider work unit progress.
func (j *CountingJob) Progress() map[string]ProviderProgress {
	completed := int(j.completed.Load())
	return map[string]ProviderProgress{
		"default": {
			TotalExpected:    j.total,
			CompletedAtStart: 0,
			Queued:           j.total - completed,
			Completed:        completed,
			Failed:           0,
		},
	}
}

// MetricsFor returns nil for counting jobs (no metrics in tests).
func (j *CountingJob) MetricsFor() *WorkUnitMetrics {
	return nil
}

var _ Job = (*CountingJob)(nil)
