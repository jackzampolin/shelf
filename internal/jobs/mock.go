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

// MultiPhaseJob simulates a real book processing workflow:
// Phase 1: OCR work units (one per page)
// Phase 2: LLM work units (created as OCR completes)
// This tests the dynamic work unit creation via OnComplete.
type MultiPhaseJob struct {
	id           string
	ocrPages     int  // Number of OCR work units in phase 1
	llmPerOCR    int  // Number of LLM units to create per OCR completion
	ocrProvider  string
	llmProvider  string

	mu             sync.Mutex
	started        bool
	ocrCompleted   int
	llmCompleted   int
	llmCreated     int
	failedUnits    []string
	completedUnits []string
}

// MultiPhaseJobConfig configures a multi-phase job.
type MultiPhaseJobConfig struct {
	ID          string
	OCRPages    int    // Number of OCR pages (default 5)
	LLMPerOCR   int    // LLM units per OCR completion (default 1)
	OCRProvider string // Specific OCR provider (empty = any)
	LLMProvider string // Specific LLM provider (empty = any)
}

// NewMultiPhaseJob creates a job that simulates OCR→LLM workflow.
func NewMultiPhaseJob(cfg MultiPhaseJobConfig) *MultiPhaseJob {
	id := cfg.ID
	if id == "" {
		id = uuid.New().String()
	}
	ocrPages := cfg.OCRPages
	if ocrPages <= 0 {
		ocrPages = 5
	}
	llmPerOCR := cfg.LLMPerOCR
	if llmPerOCR <= 0 {
		llmPerOCR = 1
	}

	return &MultiPhaseJob{
		id:          id,
		ocrPages:    ocrPages,
		llmPerOCR:   llmPerOCR,
		ocrProvider: cfg.OCRProvider,
		llmProvider: cfg.LLMProvider,
	}
}

func (j *MultiPhaseJob) ID() string   { return j.id }
func (j *MultiPhaseJob) Type() string { return "multi-phase" }

// Start returns the initial OCR work units.
func (j *MultiPhaseJob) Start(ctx context.Context) ([]WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	if j.started {
		return nil, fmt.Errorf("job already started")
	}
	j.started = true

	units := make([]WorkUnit, j.ocrPages)
	for i := 0; i < j.ocrPages; i++ {
		units[i] = WorkUnit{
			ID:       fmt.Sprintf("%s-ocr-%d", j.id, i),
			Type:     WorkUnitTypeOCR,
			Provider: j.ocrProvider,
			JobID:    j.id,
			OCRRequest: &OCRWorkRequest{
				Image:   []byte(fmt.Sprintf("page-%d-image-data", i)),
				PageNum: i + 1,
			},
		}
	}

	return units, nil
}

// OnComplete handles work unit completion.
// When an OCR unit completes, creates LLM work units.
func (j *MultiPhaseJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	j.completedUnits = append(j.completedUnits, result.WorkUnitID)

	if !result.Success {
		j.failedUnits = append(j.failedUnits, result.WorkUnitID)
		return nil, nil // Don't create follow-up work for failures
	}

	// Check if this was an OCR unit
	if result.OCRResult != nil {
		j.ocrCompleted++

		// Create LLM work units for this completed OCR
		units := make([]WorkUnit, j.llmPerOCR)
		for i := 0; i < j.llmPerOCR; i++ {
			units[i] = WorkUnit{
				ID:       fmt.Sprintf("%s-llm-%d-%d", j.id, j.ocrCompleted-1, i),
				Type:     WorkUnitTypeLLM,
				Provider: j.llmProvider,
				JobID:    j.id,
				ChatRequest: &providers.ChatRequest{
					Messages: []providers.Message{
						{Role: "user", Content: fmt.Sprintf("Process OCR result from page %d", j.ocrCompleted)},
					},
				},
			}
			j.llmCreated++
		}
		return units, nil
	}

	// LLM unit completed
	if result.ChatResult != nil {
		j.llmCompleted++
	}

	return nil, nil
}

// Done returns true when all work is complete.
func (j *MultiPhaseJob) Done() bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.done()
}

// done is the internal version that assumes lock is held.
func (j *MultiPhaseJob) done() bool {
	expectedLLM := j.ocrCompleted * j.llmPerOCR
	return j.started && j.ocrCompleted >= j.ocrPages && j.llmCompleted >= expectedLLM
}

// Status returns current progress.
func (j *MultiPhaseJob) Status(ctx context.Context) (map[string]string, error) {
	j.mu.Lock()
	defer j.mu.Unlock()

	expectedLLM := j.ocrPages * j.llmPerOCR
	return map[string]string{
		"ocr_completed": fmt.Sprintf("%d", j.ocrCompleted),
		"ocr_total":     fmt.Sprintf("%d", j.ocrPages),
		"llm_completed": fmt.Sprintf("%d", j.llmCompleted),
		"llm_total":     fmt.Sprintf("%d", expectedLLM),
		"llm_created":   fmt.Sprintf("%d", j.llmCreated),
		"failed":        fmt.Sprintf("%d", len(j.failedUnits)),
		"done":          fmt.Sprintf("%t", j.done()),
	}, nil
}

// Stats returns detailed statistics for testing.
func (j *MultiPhaseJob) Stats() (ocrCompleted, llmCompleted, failed int) {
	j.mu.Lock()
	defer j.mu.Unlock()
	return j.ocrCompleted, j.llmCompleted, len(j.failedUnits)
}

var _ Job = (*MultiPhaseJob)(nil)
