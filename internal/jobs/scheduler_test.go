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
		Logger:    slog.Default(),
		QueueSize: 100,
	})

	// Only add LLM worker - no OCR worker
	llmClient := providers.NewMockClient()
	llmWorker, _ := NewWorker(WorkerConfig{Name: "llm", LLMClient: llmClient, RPM: 6000})
	scheduler.RegisterWorker(llmWorker)

	// Create job that needs OCR
	job := NewMultiPhaseJob(MultiPhaseJobConfig{
		ID:       "no-ocr-worker",
		OCRPages: 2,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go scheduler.RunWorkers(ctx, 1)

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
	scheduler := NewScheduler(SchedulerConfig{QueueSize: 100})

	llmClient := providers.NewMockClient()
	llmClient.Latency = 100 * time.Millisecond // Slow to allow status check
	llmWorker, _ := NewWorker(WorkerConfig{Name: "llm", LLMClient: llmClient, RPM: 6000})
	scheduler.RegisterWorker(llmWorker)

	job := NewCountingJob("status-test", 5)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.RunWorkers(ctx, 1)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Check status while running
	time.Sleep(50 * time.Millisecond)

	status, err := scheduler.JobStatus(ctx, "status-test")
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
	scheduler := NewScheduler(SchedulerConfig{QueueSize: 100})

	llmClient := providers.NewMockClient()
	llmClient.Latency = 50 * time.Millisecond
	llmWorker, _ := NewWorker(WorkerConfig{Name: "llm", LLMClient: llmClient, RPM: 6000})
	scheduler.RegisterWorker(llmWorker)

	if scheduler.ActiveJobs() != 0 {
		t.Error("should start with 0 active jobs")
	}

	job1 := NewCountingJob("job1", 3)
	job2 := NewCountingJob("job2", 3)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.RunWorkers(ctx, 2)

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

// TestScheduler_PendingCount tests queue monitoring.
func TestScheduler_PendingCount(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{QueueSize: 100})

	if scheduler.PendingCount() != 0 {
		t.Error("should start with 0 pending")
	}

	// Don't start workers - items will stay in queue
	llmClient := providers.NewMockClient()
	llmWorker, _ := NewWorker(WorkerConfig{Name: "llm", LLMClient: llmClient, RPM: 6000})
	scheduler.RegisterWorker(llmWorker)

	job := NewCountingJob("pending-test", 5)

	ctx := context.Background()
	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Without workers running, items stay in queue
	if scheduler.PendingCount() != 5 {
		t.Errorf("PendingCount() = %d, want 5", scheduler.PendingCount())
	}
}

// TestScheduler_RegisterFactory tests job factory registration.
func TestScheduler_RegisterFactory(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{})

	factory := func(id string, metadata map[string]any) (Job, error) {
		return NewMockJob(MockJobConfig{ID: id}), nil
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
	llmWorker, _ := NewWorker(WorkerConfig{Name: "test-llm", LLMClient: llmClient})
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
	w1, _ := NewWorker(WorkerConfig{Name: "w1", LLMClient: llmClient})
	w2, _ := NewWorker(WorkerConfig{Name: "w2", LLMClient: llmClient})

	scheduler.RegisterWorker(w1)
	scheduler.RegisterWorker(w2)

	names := scheduler.ListWorkers()
	if len(names) != 2 {
		t.Errorf("got %d workers, want 2", len(names))
	}
}
