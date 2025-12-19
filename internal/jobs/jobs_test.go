package jobs

import (
	"context"
	"log/slog"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

func TestMockJob(t *testing.T) {
	t.Run("start creates work units", func(t *testing.T) {
		job := NewMockJob(MockJobConfig{
			WorkUnits: 3,
			UnitType:  WorkUnitTypeLLM,
		})
		job.SetRecordID("test-job") // Set ID for testing

		units, err := job.Start(context.Background())
		if err != nil {
			t.Fatalf("Start() error = %v", err)
		}

		if len(units) != 3 {
			t.Errorf("got %d work units, want 3", len(units))
		}

		for i, u := range units {
			if u.Type != WorkUnitTypeLLM {
				t.Errorf("unit %d type = %s, want llm", i, u.Type)
			}
			if u.ChatRequest == nil {
				t.Errorf("unit %d missing ChatRequest", i)
			}
		}
	})

	t.Run("cannot start twice", func(t *testing.T) {
		job := NewMockJob(MockJobConfig{WorkUnits: 2})

		_, err := job.Start(context.Background())
		if err != nil {
			t.Fatalf("first Start() error = %v", err)
		}

		_, err = job.Start(context.Background())
		if err == nil {
			t.Error("second Start() should fail")
		}
	})

	t.Run("tracks completion", func(t *testing.T) {
		job := NewMockJob(MockJobConfig{
			WorkUnits: 3,
		})
		job.SetRecordID("test-job") // Set ID for testing

		units, _ := job.Start(context.Background())

		if job.Done() {
			t.Error("job should not be done before completions")
		}

		// Complete all work units
		for _, u := range units {
			_, err := job.OnComplete(context.Background(), WorkResult{
				WorkUnitID: u.ID,
				Success:    true,
			})
			if err != nil {
				t.Fatalf("OnComplete() error = %v", err)
			}
		}

		if !job.Done() {
			t.Error("job should be done after all completions")
		}

		status, _ := job.Status(context.Background())
		if status["completed"] != "3" {
			t.Errorf("status completed = %s, want 3", status["completed"])
		}
		if status["done"] != "true" {
			t.Errorf("status done = %s, want true", status["done"])
		}
	})

	t.Run("OCR work units", func(t *testing.T) {
		job := NewMockJob(MockJobConfig{
			WorkUnits: 2,
			UnitType:  WorkUnitTypeOCR,
		})

		units, _ := job.Start(context.Background())

		for i, u := range units {
			if u.Type != WorkUnitTypeOCR {
				t.Errorf("unit %d type = %s, want ocr", i, u.Type)
			}
			if u.OCRRequest == nil {
				t.Errorf("unit %d missing OCRRequest", i)
			}
		}
	})
}

func TestWorker(t *testing.T) {
	t.Run("LLM worker processes chat requests", func(t *testing.T) {
		client := providers.NewMockClient()
		client.ResponseText = "hello world"

		worker, err := NewProviderWorker(ProviderWorkerConfig{
			LLMClient: client,
			RPS: 10.0, // 10 per second for fast tests
		})
		if err != nil {
			t.Fatalf("NewProviderWorker() error = %v", err)
		}

		if worker.Type() != WorkerTypeLLM {
			t.Errorf("Type() = %s, want llm", worker.Type())
		}

		unit := &WorkUnit{
			ID:   "test-unit",
			Type: WorkUnitTypeLLM,
			ChatRequest: &providers.ChatRequest{
				Messages: []providers.Message{
					{Role: "user", Content: "test"},
				},
			},
		}

		result := worker.Process(context.Background(), unit)

		if !result.Success {
			t.Errorf("Process() failed: %v", result.Error)
		}
		if result.ChatResult == nil {
			t.Error("missing ChatResult")
		}
		if result.ChatResult.Content != "hello world" {
			t.Errorf("Content = %q, want %q", result.ChatResult.Content, "hello world")
		}
	})

	t.Run("OCR worker processes images", func(t *testing.T) {
		provider := providers.NewMockOCRProvider()
		provider.ResponseText = "extracted text"

		worker, err := NewProviderWorker(ProviderWorkerConfig{
			OCRProvider: provider,
		})
		if err != nil {
			t.Fatalf("NewProviderWorker() error = %v", err)
		}

		if worker.Type() != WorkerTypeOCR {
			t.Errorf("Type() = %s, want ocr", worker.Type())
		}

		unit := &WorkUnit{
			ID:   "test-unit",
			Type: WorkUnitTypeOCR,
			OCRRequest: &OCRWorkRequest{
				Image:   []byte("fake image"),
				PageNum: 1,
			},
		}

		result := worker.Process(context.Background(), unit)

		if !result.Success {
			t.Errorf("Process() failed: %v", result.Error)
		}
		if result.OCRResult == nil {
			t.Error("missing OCRResult")
		}
	})

	t.Run("rejects mismatched work type", func(t *testing.T) {
		client := providers.NewMockClient()
		worker, _ := NewProviderWorker(ProviderWorkerConfig{LLMClient: client})

		unit := &WorkUnit{
			ID:   "test-unit",
			Type: WorkUnitTypeOCR, // Wrong type for LLM worker
		}

		result := worker.Process(context.Background(), unit)

		if result.Success {
			t.Error("should fail for mismatched type")
		}
	})

	t.Run("respects context cancellation", func(t *testing.T) {
		client := providers.NewMockClient()
		client.Latency = 5 * time.Second

		worker, _ := NewProviderWorker(ProviderWorkerConfig{LLMClient: client, RPS: 10.0})

		ctx, cancel := context.WithCancel(context.Background())
		cancel() // Cancel immediately

		unit := &WorkUnit{
			ID:   "test-unit",
			Type: WorkUnitTypeLLM,
			ChatRequest: &providers.ChatRequest{
				Messages: []providers.Message{{Role: "user", Content: "test"}},
			},
		}

		result := worker.Process(ctx, unit)

		if result.Success {
			t.Error("should fail when context cancelled")
		}
	})
}

func TestScheduler(t *testing.T) {
	t.Run("register and list workers", func(t *testing.T) {
		scheduler := NewScheduler(SchedulerConfig{})

		client := providers.NewMockClient()
		worker, _ := NewProviderWorker(ProviderWorkerConfig{Name: "test-llm", LLMClient: client})
		scheduler.RegisterWorker(worker)

		names := scheduler.ListWorkers()
		if len(names) != 1 || names[0] != "test-llm" {
			t.Errorf("ListWorkers() = %v, want [test-llm]", names)
		}

		w, ok := scheduler.GetWorker("test-llm")
		if !ok {
			t.Error("GetWorker() not found")
		}
		if w.Name() != "test-llm" {
			t.Errorf("Name() = %s, want test-llm", w.Name())
		}
	})

	t.Run("processes job work units", func(t *testing.T) {
		scheduler := NewScheduler(SchedulerConfig{
			Logger: slog.Default(),
		})

		// Add a worker
		client := providers.NewMockClient()
		client.Latency = time.Millisecond
		worker, _ := NewProviderWorker(ProviderWorkerConfig{
			Name:      "mock",
			LLMClient: client,
			RPS: 100.0, // Fast for tests
		})
		scheduler.RegisterWorker(worker)

		// Create and submit a job
		job := NewCountingJob(5)

		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		// Start scheduler (workers run as their own goroutines)
		go scheduler.Start(ctx)

		// Submit job
		err := scheduler.Submit(ctx, job)
		if err != nil {
			t.Fatalf("Submit() error = %v", err)
		}

		// Wait for completion
		for i := 0; i < 50; i++ {
			if job.Done() {
				break
			}
			time.Sleep(50 * time.Millisecond)
		}

		if !job.Done() {
			t.Errorf("job not done, completed %d/5", job.Completed())
		}

		if job.Completed() != 5 {
			t.Errorf("Completed() = %d, want 5", job.Completed())
		}
	})

	t.Run("routes to specific provider", func(t *testing.T) {
		scheduler := NewScheduler(SchedulerConfig{})

		// Add two workers
		client1 := providers.NewMockClient()
		client1.Latency = time.Millisecond
		worker1, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm-1", LLMClient: client1, RPS: 100.0})
		scheduler.RegisterWorker(worker1)

		client2 := providers.NewMockClient()
		client2.Latency = time.Millisecond
		worker2, _ := NewProviderWorker(ProviderWorkerConfig{Name: "llm-2", LLMClient: client2, RPS: 100.0})
		scheduler.RegisterWorker(worker2)

		// Create job that targets specific provider
		job := NewMockJob(MockJobConfig{
			WorkUnits: 3,
			Provider:  "llm-2", // Target specific worker
		})

		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		go scheduler.Start(ctx)

		err := scheduler.Submit(ctx, job)
		if err != nil {
			t.Fatalf("Submit() error = %v", err)
		}

		// Wait for completion
		for i := 0; i < 50; i++ {
			if job.Done() {
				break
			}
			time.Sleep(50 * time.Millisecond)
		}

		if !job.Done() {
			t.Error("job not done")
		}

		// All requests should have gone to client2
		if client2.RequestCount() != 3 {
			t.Errorf("client2 got %d requests, want 3", client2.RequestCount())
		}
		if client1.RequestCount() != 0 {
			t.Errorf("client1 got %d requests, want 0", client1.RequestCount())
		}
	})
}

func TestNewRecord(t *testing.T) {
	metadata := map[string]any{"key": "value"}
	record := NewRecord("test", metadata)

	if record.JobType != "test" {
		t.Errorf("JobType = %s, want test", record.JobType)
	}
	if record.Status != StatusQueued {
		t.Errorf("Status = %s, want queued", record.Status)
	}
	if record.CreatedAt.IsZero() {
		t.Error("CreatedAt is zero")
	}
	if record.Metadata["key"] != "value" {
		t.Error("metadata not preserved")
	}
}
