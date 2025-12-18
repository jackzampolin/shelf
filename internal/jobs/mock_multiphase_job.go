package jobs

import (
	"context"
	"fmt"
	"sync"

	"github.com/jackzampolin/shelf/internal/providers"
)

// MultiPhaseJob simulates a real book processing workflow:
// Phase 1: OCR work units (one per page)
// Phase 2: LLM work units (created as OCR completes)
// This tests the dynamic work unit creation via OnComplete.
type MultiPhaseJob struct {
	id          string // DefraDB record ID (set by scheduler after persistence)
	ocrPages    int    // Number of OCR work units in phase 1
	llmPerOCR   int    // Number of LLM units to create per OCR completion
	ocrProvider string
	llmProvider string

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
	OCRPages    int    // Number of OCR pages (default 5)
	LLMPerOCR   int    // LLM units per OCR completion (default 1)
	OCRProvider string // Specific OCR provider (empty = any)
	LLMProvider string // Specific LLM provider (empty = any)
}

// NewMultiPhaseJob creates a job that simulates OCR→LLM workflow.
func NewMultiPhaseJob(cfg MultiPhaseJobConfig) *MultiPhaseJob {
	ocrPages := cfg.OCRPages
	if ocrPages <= 0 {
		ocrPages = 5
	}
	llmPerOCR := cfg.LLMPerOCR
	if llmPerOCR <= 0 {
		llmPerOCR = 1
	}

	return &MultiPhaseJob{
		ocrPages:    ocrPages,
		llmPerOCR:   llmPerOCR,
		ocrProvider: cfg.OCRProvider,
		llmProvider: cfg.LLMProvider,
	}
}

// ID returns the DefraDB record ID. Empty until persisted.
func (j *MultiPhaseJob) ID() string {
	return j.id
}

// SetRecordID sets the DefraDB record ID after persistence.
func (j *MultiPhaseJob) SetRecordID(id string) {
	j.id = id
}

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

// Progress returns per-provider work unit progress.
func (j *MultiPhaseJob) Progress() map[string]ProviderProgress {
	j.mu.Lock()
	defer j.mu.Unlock()

	ocrProvider := j.ocrProvider
	if ocrProvider == "" {
		ocrProvider = "ocr-default"
	}
	llmProvider := j.llmProvider
	if llmProvider == "" {
		llmProvider = "llm-default"
	}

	expectedLLM := j.ocrPages * j.llmPerOCR

	// Count OCR failures
	ocrFailed := 0
	llmFailed := 0
	for _, id := range j.failedUnits {
		if len(id) > 4 && id[len(j.id)+1:len(j.id)+4] == "ocr" {
			ocrFailed++
		} else {
			llmFailed++
		}
	}

	return map[string]ProviderProgress{
		ocrProvider: {
			TotalExpected:    j.ocrPages,
			CompletedAtStart: 0,
			Queued:           j.ocrPages - j.ocrCompleted - ocrFailed,
			Completed:        j.ocrCompleted,
			Failed:           ocrFailed,
		},
		llmProvider: {
			TotalExpected:    expectedLLM,
			CompletedAtStart: 0,
			Queued:           j.llmCreated - j.llmCompleted - llmFailed,
			Completed:        j.llmCompleted,
			Failed:           llmFailed,
		},
	}
}

// MetricsFor returns nil for multi-phase jobs (no metrics in tests).
func (j *MultiPhaseJob) MetricsFor() *WorkUnitMetrics {
	return nil
}

var _ Job = (*MultiPhaseJob)(nil)
