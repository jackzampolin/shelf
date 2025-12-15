package jobs

import (
	"context"
	"fmt"
	"sync"
	"sync/atomic"

	"github.com/google/uuid"
	"github.com/jackzampolin/shelf/internal/providers"
)

const MockJobType = "mock"

// MockJob is a simple job for testing the job system.
// It creates N work units and tracks their completion.
type MockJob struct {
	id         string
	workUnits  int
	unitType   WorkUnitType
	provider   string
	shouldFail bool

	mu        sync.Mutex
	started   bool
	completed int
	results   []WorkResult
}

// MockJobConfig configures a mock job.
type MockJobConfig struct {
	ID         string       // Job ID (auto-generated if empty)
	WorkUnits  int          // Number of work units to create
	UnitType   WorkUnitType // Type of work units (default: LLM)
	Provider   string       // Provider to use (empty = any)
	ShouldFail bool         // If true, job fails after all work completes
}

// NewMockJob creates a new mock job with default settings.
func NewMockJob(cfg MockJobConfig) *MockJob {
	id := cfg.ID
	if id == "" {
		id = uuid.New().String()
	}
	unitType := cfg.UnitType
	if unitType == "" {
		unitType = WorkUnitTypeLLM
	}
	workUnits := cfg.WorkUnits
	if workUnits <= 0 {
		workUnits = 5
	}

	return &MockJob{
		id:         id,
		workUnits:  workUnits,
		unitType:   unitType,
		provider:   cfg.Provider,
		shouldFail: cfg.ShouldFail,
	}
}

func (j *MockJob) ID() string {
	return j.id
}

func (j *MockJob) Type() string {
	return MockJobType
}

// Start creates initial work units.
func (j *MockJob) Start(ctx context.Context) ([]WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	if j.started {
		return nil, fmt.Errorf("job already started")
	}
	j.started = true

	units := make([]WorkUnit, j.workUnits)
	for i := 0; i < j.workUnits; i++ {
		units[i] = WorkUnit{
			ID:       fmt.Sprintf("%s-unit-%d", j.id, i),
			Type:     j.unitType,
			Provider: j.provider,
			JobID:    j.id,
		}

		// Add appropriate request based on type
		if j.unitType == WorkUnitTypeLLM {
			units[i].ChatRequest = &providers.ChatRequest{
				Messages: []providers.Message{
					{Role: "user", Content: fmt.Sprintf("Mock request %d", i)},
				},
			}
		} else {
			units[i].OCRRequest = &OCRWorkRequest{
				Image:   []byte(fmt.Sprintf("mock-image-%d", i)),
				PageNum: i + 1,
			}
		}
	}

	return units, nil
}

// OnComplete handles work unit completion.
func (j *MockJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	j.completed++
	j.results = append(j.results, result)

	// MockJob doesn't create follow-up work
	return nil, nil
}

// Done returns true when all work is complete.
func (j *MockJob) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()

	return j.started && j.completed >= j.workUnits
}

// Status returns current progress.
func (j *MockJob) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	return map[string]string{
		"completed": fmt.Sprintf("%d", j.completed),
		"total":     fmt.Sprintf("%d", j.workUnits),
		"started":   fmt.Sprintf("%t", j.started),
		"done":      fmt.Sprintf("%t", j.started && j.completed >= j.workUnits),
	}, nil
}

// Results returns all collected results (for testing).
func (j *MockJob) Results() []WorkResult {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.results
}

// Verify interface
var _ Job = (*MockJob)(nil)

// CountingJob is a simple job that counts work unit completions.
// Useful for testing the scheduler.
type CountingJob struct {
	id        string
	total     int
	completed atomic.Int32
	done      atomic.Bool
}

func NewCountingJob(id string, total int) *CountingJob {
	return &CountingJob{
		id:    id,
		total: total,
	}
}

func (j *CountingJob) ID() string   { return j.id }
func (j *CountingJob) Type() string { return "counting" }

func (j *CountingJob) Start(ctx context.Context) ([]WorkUnit, error) {
	units := make([]WorkUnit, j.total)
	for i := 0; i < j.total; i++ {
		units[i] = WorkUnit{
			ID:   fmt.Sprintf("%s-unit-%d", j.id, i),
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

var _ Job = (*CountingJob)(nil)
