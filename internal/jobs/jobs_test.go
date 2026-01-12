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

func TestProviderWorkerPool(t *testing.T) {
	t.Run("LLM pool type", func(t *testing.T) {
		client := providers.NewMockClient()

		pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:      "test-llm",
			LLMClient: client,
		})
		if err != nil {
			t.Fatalf("NewProviderWorkerPool() error = %v", err)
		}

		if pool.Type() != PoolTypeLLM {
			t.Errorf("Type() = %s, want llm", pool.Type())
		}
		if pool.Name() != "test-llm" {
			t.Errorf("Name() = %s, want test-llm", pool.Name())
		}
	})

	t.Run("OCR pool type", func(t *testing.T) {
		provider := providers.NewMockOCRProvider()

		pool, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:        "test-ocr",
			OCRProvider: provider,
		})
		if err != nil {
			t.Fatalf("NewProviderWorkerPool() error = %v", err)
		}

		if pool.Type() != PoolTypeOCR {
			t.Errorf("Type() = %s, want ocr", pool.Type())
		}
	})

	t.Run("requires client or provider", func(t *testing.T) {
		_, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name: "test",
		})
		if err == nil {
			t.Error("should fail without client or provider")
		}
	})

	t.Run("cannot have both client and provider", func(t *testing.T) {
		client := providers.NewMockClient()
		provider := providers.NewMockOCRProvider()

		_, err := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:        "test",
			LLMClient:   client,
			OCRProvider: provider,
		})
		if err == nil {
			t.Error("should fail with both client and provider")
		}
	})
}

func TestScheduler(t *testing.T) {
	t.Run("register and list pools", func(t *testing.T) {
		scheduler := NewScheduler(SchedulerConfig{})

		client := providers.NewMockClient()
		pool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "test-llm", LLMClient: client})
		scheduler.RegisterPool(pool)

		names := scheduler.ListPools()
		if len(names) != 1 || names[0] != "test-llm" {
			t.Errorf("ListPools() = %v, want [test-llm]", names)
		}

		p, ok := scheduler.GetPool("test-llm")
		if !ok {
			t.Error("GetPool() not found")
		}
		if p.Name() != "test-llm" {
			t.Errorf("Name() = %s, want test-llm", p.Name())
		}
	})

	t.Run("processes job work units", func(t *testing.T) {
		scheduler := NewScheduler(SchedulerConfig{
			Logger: slog.Default(),
		})

		// Add a pool
		client := providers.NewMockClient()
		client.Latency = time.Millisecond
		pool, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{
			Name:      "mock",
			LLMClient: client,
			RPS:       100.0, // Fast for tests
		})
		scheduler.RegisterPool(pool)

		// Create and submit a job
		job := NewCountingJob(5)

		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		// Start scheduler (pools run as their own goroutines)
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

		// Add two pools
		client1 := providers.NewMockClient()
		client1.Latency = time.Millisecond
		pool1, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm-1", LLMClient: client1, RPS: 100.0})
		scheduler.RegisterPool(pool1)

		client2 := providers.NewMockClient()
		client2.Latency = time.Millisecond
		pool2, _ := NewProviderWorkerPool(ProviderWorkerPoolConfig{Name: "llm-2", LLMClient: client2, RPS: 100.0})
		scheduler.RegisterPool(pool2)

		// Create job that targets specific provider
		job := NewMockJob(MockJobConfig{
			WorkUnits: 3,
			Provider:  "llm-2", // Target specific pool
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
