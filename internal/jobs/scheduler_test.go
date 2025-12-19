package jobs

import (
	"context"
	"log/slog"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

// TestScheduler_NoWorkerForType tests error handling when no worker available.
func TestScheduler_NoWorkerForType(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{
		Logger: slog.Default(),
	})

	// Only add LLM worker - no OCR worker
	llmClient := providers.NewMockClient()
	llmWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterWorker(llmWorker)

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
		t.Errorf("failed = %d, want 2 (no OCR worker)", failed)
	}
}

// TestScheduler_JobStatus tests job status reporting.
func TestScheduler_JobStatus(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	llmClient := providers.NewMockClient()
	llmClient.Latency = 100 * time.Millisecond // Slow to allow status check
	llmWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterWorker(llmWorker)

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
	llmWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterWorker(llmWorker)

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

// TestScheduler_WorkerQueueDepth tests that work stays in worker queue when not started.
func TestScheduler_WorkerQueueDepth(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	// Register worker but don't start scheduler - items will stay in worker's queue
	llmClient := providers.NewMockClient()
	llmWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm", LLMClient: llmClient, RPS: 100.0})
	scheduler.RegisterWorker(llmWorker)

	job := NewCountingJob(5)

	ctx := context.Background()
	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Wait for async job start to complete (Submit spawns a goroutine)
	time.Sleep(50 * time.Millisecond)

	// Without starting scheduler, items stay in worker's queue
	status := scheduler.WorkerStatus()
	if status["llm"].QueueDepth != 5 {
		t.Errorf("QueueDepth = %d, want 5", status["llm"].QueueDepth)
	}
}

// TestScheduler_RegisterFactory tests job factory registration.
func TestScheduler_RegisterFactory(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	factory := func(id string, metadata map[string]any) (Job, error) {
		job := NewMockJob(MockJobConfig{})
		job.SetRecordID(id) // Set the persisted ID
		return job, nil
	}

	scheduler.RegisterFactory("test-type", factory)

	// No direct way to verify registration, but it shouldn't panic
}

// TestScheduler_GetWorker tests worker lookup.
func TestScheduler_GetWorker(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	// Not found initially
	_, ok := scheduler.GetWorker("nonexistent")
	if ok {
		t.Error("should not find nonexistent worker")
	}

	// Register and find
	llmClient := providers.NewMockClient()
	llmWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "test-llm", LLMClient: llmClient})
	scheduler.RegisterWorker(llmWorker)

	w, ok := scheduler.GetWorker("test-llm")
	if !ok {
		t.Error("should find registered worker")
	}
	if w.Name() != "test-llm" {
		t.Errorf("Name() = %s, want test-llm", w.Name())
	}
}

// TestScheduler_ListWorkers tests worker enumeration.
func TestScheduler_ListWorkers(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	if len(scheduler.ListWorkers()) != 0 {
		t.Error("should start with no workers")
	}

	llmClient := providers.NewMockClient()
	w1, _ := NewProviderWorker(ProviderWorkerConfig{Name: "w1", LLMClient: llmClient})
	w2, _ := NewProviderWorker(ProviderWorkerConfig{Name: "w2", LLMClient: llmClient})

	scheduler.RegisterWorker(w1)
	scheduler.RegisterWorker(w2)

	names := scheduler.ListWorkers()
	if len(names) != 2 {
		t.Errorf("got %d workers, want 2", len(names))
	}
}

// TestScheduler_WorkerStatus tests worker status reporting.
func TestScheduler_WorkerStatus(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	llmClient := providers.NewMockClient()
	ocrProvider := providers.NewMockOCRProvider()

	llmWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm-1", LLMClient: llmClient, RPS: 1.0})
	ocrWorker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "ocr-1", OCRProvider: ocrProvider})

	scheduler.RegisterWorker(llmWorker)
	scheduler.RegisterWorker(ocrWorker)

	status := scheduler.WorkerStatus()

	if len(status) != 2 {
		t.Errorf("got %d workers in status, want 2", len(status))
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

// TestScheduler_InitFromRegistry tests automatic worker creation from registry.
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

	// Verify workers were created
	workers := scheduler.ListWorkers()
	if len(workers) != 2 {
		t.Errorf("got %d workers, want 2", len(workers))
	}

	// Verify LLM worker
	llmWorkerIface, ok := scheduler.GetWorker("openrouter")
	if !ok {
		t.Error("openrouter worker not found")
	} else {
		if llmWorkerIface.Type() != WorkerTypeLLM {
			t.Errorf("openrouter Type = %s, want llm", llmWorkerIface.Type())
		}
		// Verify rate limit was passed through (cast to *Worker for rate limiter access)
		if llmWorker, ok := llmWorkerIface.(*ProviderWorker); ok {
			status := llmWorker.RateLimiterStatus()
			if status.RPS != 120 {
				t.Errorf("openrouter RPS = %f, want 120", status.RPS)
			}
		} else {
			t.Error("openrouter worker is not a *ProviderWorker")
		}
	}

	// Verify OCR worker
	ocrWorkerIface, ok := scheduler.GetWorker("mistral")
	if !ok {
		t.Error("mistral worker not found")
	} else {
		if ocrWorkerIface.Type() != WorkerTypeOCR {
			t.Errorf("mistral Type = %s, want ocr", ocrWorkerIface.Type())
		}
		// Verify rate limit was passed through (cast to *Worker for rate limiter access)
		if ocrWorker, ok := ocrWorkerIface.(*ProviderWorker); ok {
			status := ocrWorker.RateLimiterStatus()
			if status.RPS != 10.0 {
				t.Errorf("mistral RPS = %f, want 10.0", status.RPS)
			}
		} else {
			t.Error("mistral worker is not a *ProviderWorker")
		}
	}
}
