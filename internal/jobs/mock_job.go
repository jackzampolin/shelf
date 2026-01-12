package jobs

import (
	"context"
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/providers"
)

const MockJobType = "mock"

// MockJob is a simple job for testing the job system.
// It creates N work units and tracks their completion.
type MockJob struct {
	id         string // DefraDB record ID (set by scheduler after persistence)
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
	WorkUnits  int          // Number of work units to create
	UnitType   WorkUnitType // Type of work units (default: LLM)
	Provider   string       // Provider to use (empty = any)
	ShouldFail bool         // If true, job fails after all work completes
}

// NewMockJob creates a new mock job with default settings.
func NewMockJob(cfg MockJobConfig) *MockJob {
	unitType := cfg.UnitType
	if unitType == "" {
		unitType = WorkUnitTypeLLM
	}
	workUnits := cfg.WorkUnits
	if workUnits <= 0 {
		workUnits = 5
	}

	return &MockJob{
		workUnits:  workUnits,
		unitType:   unitType,
		provider:   cfg.Provider,
		shouldFail: cfg.ShouldFail,
	}
}

// ID returns the DefraDB record ID. Empty until persisted.
func (j *MockJob) ID() string {
	return j.id
}

// SetRecordID sets the DefraDB record ID after persistence.
func (j *MockJob) SetRecordID(id string) {
	j.id = id
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

	jobID := j.ID()
	units := make([]WorkUnit, j.workUnits)
	for i := 0; i < j.workUnits; i++ {
		units[i] = WorkUnit{
			ID:       fmt.Sprintf("%s-unit-%d", jobID, i),
			Type:     j.unitType,
			Provider: j.provider,
			JobID:    jobID,
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

// Progress returns per-provider work unit progress.
func (j *MockJob) Progress() map[string]ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()

	provider := j.provider
	if provider == "" {
		provider = "default"
	}

	// Count failed from results
	failed := 0
	for _, r := range j.results {
		if !r.Success {
			failed++
		}
	}

	return map[string]ProviderProgress{
		provider: {
			TotalExpected:    j.workUnits,
			CompletedAtStart: 0,
			Queued:           j.workUnits - j.completed,
			Completed:        j.completed - failed,
			Failed:           failed,
		},
	}
}

// MetricsFor returns nil for mock jobs (no metrics in tests).
func (j *MockJob) MetricsFor() *WorkUnitMetrics {
	return nil
}

// Verify interface
var _ Job = (*MockJob)(nil)
