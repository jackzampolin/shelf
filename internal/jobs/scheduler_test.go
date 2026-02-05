package jobs

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

// TestScheduler_NoPoolForType tests error handling when no pool available.
func TestScheduler_NoPoolForType(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{
		Logger: slog.Default(),
	})

	// Only add LLM pool - no OCR pool
	llmClient := providers.NewMockClient()
	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterPool(llmPool)

	// Create job that needs OCR
	job := NewMultiPhaseJob(MultiPhaseJobConfig{
		OCRPages: 2,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go scheduler.Start(ctx)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Wait a bit - job should have failures
	time.Sleep(500 * time.Millisecond)

	_, _, failed := job.Stats()
	if failed != 2 {
		t.Errorf("failed = %d, want 2 (no OCR pool)", failed)
	}
}

// TestScheduler_JobStatus tests job status reporting.
func TestScheduler_JobStatus(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	llmClient := providers.NewMockClient()
	llmClient.Latency = 100 * time.Millisecond // Slow to allow status check
	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterPool(llmPool)

	job := NewCountingJob(5)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.Start(ctx)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Check status while running
	time.Sleep(50 * time.Millisecond)

	status, err := scheduler.JobStatus(ctx, job.ID())
	if err != nil {
		t.Fatalf("JobStatus() error = %v", err)
	}

	if status == nil {
		t.Fatal("status is nil")
	}

	// Should have pending_units key
	if _, ok := status["pending_units"]; !ok {
		t.Error("status missing pending_units")
	}
}

// TestScheduler_ActiveJobs tests active job tracking.
func TestScheduler_ActiveJobs(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	llmClient := providers.NewMockClient()
	llmClient.Latency = 50 * time.Millisecond
	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterPool(llmPool)

	if scheduler.ActiveJobs() != 0 {
		t.Error("should start with 0 active jobs")
	}

	job1 := NewCountingJob(3)
	job2 := NewCountingJob(3)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.Start(ctx)

	scheduler.Submit(ctx, job1)
	scheduler.Submit(ctx, job2)

	// Should have 2 active jobs
	time.Sleep(10 * time.Millisecond)
	if scheduler.ActiveJobs() != 2 {
		t.Errorf("ActiveJobs() = %d, want 2", scheduler.ActiveJobs())
	}

	// Wait for completion
	for i := 0; i < 100; i++ {
		if job1.Done() && job2.Done() {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	// Should have 0 active jobs after completion
	time.Sleep(100 * time.Millisecond) // Give scheduler time to clean up
	if scheduler.ActiveJobs() != 0 {
		t.Errorf("ActiveJobs() = %d after completion, want 0", scheduler.ActiveJobs())
	}
}

// TestScheduler_OnCompleteErrorRemovesJob ensures jobs are failed/removed when OnComplete returns an error.
func TestScheduler_OnCompleteErrorRemovesJob(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	llmClient := providers.NewMockClient()
	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{
		Name:      "llm",
		LLMClient: llmClient,
		RPS:       100.0,
	})
	scheduler.RegisterPool(llmPool)

	job := &OnCompleteErrorJob{
		onCompleteErr: errors.New("oncomplete failed"),
		doneCh:        make(chan struct{}),
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.Start(ctx)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	select {
	case <-job.doneCh:
	case <-ctx.Done():
		t.Fatal("timed out waiting for OnComplete to run")
	}

	// Give scheduler a moment to remove the failed job.
	time.Sleep(50 * time.Millisecond)

	if scheduler.ActiveJobs() != 0 {
		t.Errorf("ActiveJobs() = %d, want 0 after OnComplete failure", scheduler.ActiveJobs())
	}
}

// TestScheduler_PoolQueueDepth tests that work stays in pool queue when not started.
func TestScheduler_PoolQueueDepth(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	// Register pool but don't start scheduler - items will stay in pool's queue
	llmClient := providers.NewMockClient()
	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterPool(llmPool)

	job := NewCountingJob(5)

	ctx := context.Background()
	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Wait for async job start to complete (Submit spawns a goroutine)
	time.Sleep(50 * time.Millisecond)

	// Without starting scheduler, items stay in pool's queue
	status := scheduler.PoolStatuses()
	if status["llm"].QueueDepth != 5 {
		t.Errorf("QueueDepth = %d, want 5", status["llm"].QueueDepth)
	}
}

// TestScheduler_RegisterFactory tests job factory registration.
func TestScheduler_RegisterFactory(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	factory := func(ctx context.Context, id string, metadata map[string]any) (Job, error) {
		job := NewMockJob(MockJobConfig{})
		job.SetRecordID(id) // Set the persisted ID
		return job, nil
	}

	scheduler.RegisterFactory("test-type", factory)

	// No direct way to verify registration, but it shouldn't panic
}

// TestScheduler_GetPool tests pool lookup.
func TestScheduler_GetPool(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	// Not found initially
	_, ok := scheduler.GetPool("nonexistent")
	if ok {
		t.Error("should not find nonexistent pool")
	}

	// Register and find
	llmClient := providers.NewMockClient()
	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "test-llm", LLMClient: llmClient})
	scheduler.RegisterPool(llmPool)

	p, ok := scheduler.GetPool("test-llm")
	if !ok {
		t.Error("should find registered pool")
	}
	if p.Name() != "test-llm" {
		t.Errorf("Name() = %s, want test-llm", p.Name())
	}
}

// TestScheduler_ListPools tests pool enumeration.
func TestScheduler_ListPools(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	if len(scheduler.ListPools()) != 0 {
		t.Error("should start with no pools")
	}

	llmClient := providers.NewMockClient()
	p1, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "p1", LLMClient: llmClient})
	p2, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "p2", LLMClient: llmClient})

	scheduler.RegisterPool(p1)
	scheduler.RegisterPool(p2)

	names := scheduler.ListPools()
	if len(names) != 2 {
		t.Errorf("got %d pools, want 2", len(names))
	}
}

// TestScheduler_PoolStatus tests pool status reporting.
func TestScheduler_PoolStatus(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	llmClient := providers.NewMockClient()
	ocrProvider := providers.NewMockOCRProvider()

	llmPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm-1", LLMClient: llmClient, RPS: 1.0})
	ocrPool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "ocr-1", OCRProvider: ocrProvider})

	scheduler.RegisterPool(llmPool)
	scheduler.RegisterPool(ocrPool)

	status := scheduler.PoolStatuses()

	if len(status) != 2 {
		t.Errorf("got %d pools in status, want 2", len(status))
	}

	llmStatus, ok := status["llm-1"]
	if !ok {
		t.Error("llm-1 not in status")
	}
	if llmStatus.Type != "llm" {
		t.Errorf("llm-1 Type = %s, want llm", llmStatus.Type)
	}
	if llmStatus.RateLimiter.RPS != 1.0 {
		t.Errorf("llm-1 RPS = %f, want 1.0", llmStatus.RateLimiter.RPS)
	}
}

// TestScheduler_InitFromRegistry tests automatic pool creation from registry.
func TestScheduler_InitFromRegistry(t *testing.T) {
	// Create registry with providers
	registry := providers.NewRegistryFromConfig(providers.RegistryConfig{
		LLMProviders: map[string]providers.LLMProviderConfig{
			"openrouter": {
				Type:      "openrouter",
				APIKey:    "test-key",
				Model:     "test-model",
				RateLimit: 120, // 120 RPS
				Enabled:   true,
			},
		},
		OCRProviders: map[string]providers.OCRProviderConfig{
			"mistral": {
				Type:      "mistral-ocr",
				APIKey:    "test-key",
				RateLimit: 10.0, // 10 RPS
				Enabled:   true,
			},
		},
	})

	// Create scheduler and init from registry
	scheduler := NewScheduler(SchedulerConfig{
		Logger: slog.Default(),
	})

	if err := scheduler.InitFromRegistry(registry); err != nil {
		t.Fatalf("InitFromRegistry() error = %v", err)
	}

	// Verify pools were created
	pools := scheduler.ListPools()
	if len(pools) != 2 {
		t.Errorf("got %d pools, want 2", len(pools))
	}

	// Verify LLM pool
	llmPool, ok := scheduler.GetPool("openrouter")
	if !ok {
		t.Error("openrouter pool not found")
	} else {
		if llmPool.Type() != PoolTypeLLM {
			t.Errorf("openrouter Type = %s, want llm", llmPool.Type())
		}
		// Verify rate limit was passed through
		status := llmPool.Status()
		if status.RateLimiter.RPS != 120 {
			t.Errorf("openrouter RPS = %f, want 120", status.RateLimiter.RPS)
		}
	}

	// Verify OCR pool
	ocrPool, ok := scheduler.GetPool("mistral")
	if !ok {
		t.Error("mistral pool not found")
	} else {
		if ocrPool.Type() != PoolTypeOCR {
			t.Errorf("mistral Type = %s, want ocr", ocrPool.Type())
		}
		// Verify rate limit was passed through
		status := ocrPool.Status()
		if status.RateLimiter.RPS != 10.0 {
			t.Errorf("mistral RPS = %f, want 10.0", status.RateLimiter.RPS)
		}
	}
}

// SyncCompleteJob is a job that completes synchronously with zero work units.
// This mimics the behavior of ingest jobs.
type SyncCompleteJob struct {
	id      string
	started bool
	done    bool
}

type OnCompleteErrorJob struct {
	id            string
	doneCh        chan struct{}
	onCompleteErr error
}

func (j *OnCompleteErrorJob) ID() string                   { return j.id }
func (j *OnCompleteErrorJob) SetRecordID(id string)        { j.id = id }
func (j *OnCompleteErrorJob) Type() string                 { return "oncomplete-error" }
func (j *OnCompleteErrorJob) Done() bool                   { return false }
func (j *OnCompleteErrorJob) MetricsFor() *WorkUnitMetrics { return nil }
func (j *OnCompleteErrorJob) Status(ctx context.Context) (map[string]string, error) {
	return map[string]string{"done": "false"}, nil
}
func (j *OnCompleteErrorJob) Progress() map[string]ProviderProgress { return nil }
func (j *OnCompleteErrorJob) Start(ctx context.Context) ([]WorkUnit, error) {
	return []WorkUnit{
		{
			ID:       "oncomplete-error-unit",
			Type:     WorkUnitTypeLLM,
			Provider: "llm",
			ChatRequest: &providers.ChatRequest{
				Messages: []providers.Message{{Role: "user", Content: "trigger completion"}},
			},
		},
	}, nil
}
func (j *OnCompleteErrorJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
	select {
	case <-j.doneCh:
	default:
		close(j.doneCh)
	}
	return nil, j.onCompleteErr
}

func (j *SyncCompleteJob) ID() string                   { return j.id }
func (j *SyncCompleteJob) SetRecordID(id string)        { j.id = id }
func (j *SyncCompleteJob) Type() string                 { return "sync-complete" }
func (j *SyncCompleteJob) Done() bool                   { return j.done }
func (j *SyncCompleteJob) MetricsFor() *WorkUnitMetrics { return nil }
func (j *SyncCompleteJob) Status(ctx context.Context) (map[string]string, error) {
	return map[string]string{"done": "true"}, nil
}
func (j *SyncCompleteJob) Progress() map[string]ProviderProgress { return nil }
func (j *SyncCompleteJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
	return nil, nil
}
func (j *SyncCompleteJob) Start(ctx context.Context) ([]WorkUnit, error) {
	if j.started {
		return nil, nil
	}
	j.started = true
	j.done = true   // Immediately done
	return nil, nil // Zero work units
}

// TestScheduler_SyncCompleteJob tests jobs that complete synchronously with no work units.
// This verifies the fix for ingest jobs that never completed.
func TestScheduler_SyncCompleteJob(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{
		Logger: slog.Default(),
	})

	job := &SyncCompleteJob{}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go scheduler.Start(ctx)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Wait for async completion check
	time.Sleep(100 * time.Millisecond)

	// Verify job is no longer in active jobs (was cleaned up after sync completion)
	if scheduler.ActiveJobs() != 0 {
		t.Errorf("ActiveJobs() = %d, want 0 (job should complete synchronously)", scheduler.ActiveJobs())
	}

	// Verify job reports as done
	if !job.Done() {
		t.Error("job.Done() = false, want true")
	}
}
