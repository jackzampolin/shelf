package jobs

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// TestMultiPhaseJob_Workflow tests that OCR→LLM workflow works correctly.
func TestMultiPhaseJob_Workflow(t *testing.T) {
	t.Run("creates LLM units as OCR completes", func(t *testing.T) {
		job := NewMultiPhaseJob(MultiPhaseJobConfig{
			OCRPages:  3,
			LLMPerOCR: 2,
		})
		job.SetRecordID("test-multi") // Set ID for testing

		// Start job - should get OCR units
		units, err := job.Start(context.Background())
		if err != nil {
			t.Fatalf("Start() error = %v", err)
		}
		if len(units) != 3 {
			t.Errorf("got %d units, want 3 OCR units", len(units))
		}
		for _, u := range units {
			if u.Type != WorkUnitTypeOCR {
				t.Errorf("unit type = %s, want ocr", u.Type)
			}
		}

		if job.Done() {
			t.Error("job should not be done yet")
		}

		// Complete first OCR - should create 2 LLM units
		newUnits, err := job.OnComplete(context.Background(), WorkResult{
			WorkUnitID: units[0].ID,
			Success:    true,
			OCRResult:  &providers.OCRResult{Success: true, Text: "page 1 text"},
		})
		if err != nil {
			t.Fatalf("OnComplete() error = %v", err)
		}
		if len(newUnits) != 2 {
			t.Errorf("got %d new units, want 2 LLM units", len(newUnits))
		}
		for _, u := range newUnits {
			if u.Type != WorkUnitTypeLLM {
				t.Errorf("unit type = %s, want llm", u.Type)
			}
		}

		// Complete remaining OCR units
		for _, u := range units[1:] {
			job.OnComplete(context.Background(), WorkResult{
				WorkUnitID: u.ID,
				Success:    true,
				OCRResult:  &providers.OCRResult{Success: true},
			})
		}

		// Job not done - still need LLM completions
		if job.Done() {
			t.Error("job should not be done - LLM work pending")
		}

		// Complete all LLM units (3 OCR * 2 LLM = 6 total)
		for i := 0; i < 6; i++ {
			job.OnComplete(context.Background(), WorkResult{
				WorkUnitID: "llm-" + string(rune(i)),
				Success:    true,
				ChatResult: &providers.ChatResult{Success: true},
			})
		}

		if !job.Done() {
			ocr, llm, _ := job.Stats()
			t.Errorf("job should be done, ocr=%d llm=%d", ocr, llm)
		}
	})

	t.Run("handles failures without creating follow-up work", func(t *testing.T) {
		job := NewMultiPhaseJob(MultiPhaseJobConfig{
			OCRPages:  2,
			LLMPerOCR: 1,
		})

		units, _ := job.Start(context.Background())

		// Fail first OCR - should not create LLM units
		newUnits, _ := job.OnComplete(context.Background(), WorkResult{
			WorkUnitID: units[0].ID,
			Success:    false,
			Error:      nil,
		})
		if len(newUnits) != 0 {
			t.Errorf("got %d units for failed OCR, want 0", len(newUnits))
		}

		_, _, failed := job.Stats()
		if failed != 1 {
			t.Errorf("failed = %d, want 1", failed)
		}
	})
}

// TestScheduler_MultiPhaseWorkflow tests the full scheduler with mixed workers.
func TestScheduler_MultiPhaseWorkflow(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{
		Logger:    slog.Default(),
		QueueSize: 100,
	})

	// Create OCR worker
	ocrProvider := providers.NewMockOCRProvider()
	ocrProvider.ResponseText = "extracted text"
	ocrWorker, _ := NewWorker(WorkerConfig{
		Name:        "ocr-paddle",
		OCRProvider: ocrProvider,
	})
	scheduler.RegisterWorker(ocrWorker)

	// Create LLM worker
	llmClient := providers.NewMockClient()
	llmClient.ResponseText = "processed result"
	llmClient.Latency = time.Millisecond
	llmWorker, _ := NewWorker(WorkerConfig{
		Name:      "llm-openrouter",
		LLMClient: llmClient,
		RPM:       6000,
	})
	scheduler.RegisterWorker(llmWorker)

	// Verify both workers registered
	workers := scheduler.ListWorkers()
	if len(workers) != 2 {
		t.Fatalf("expected 2 workers, got %d", len(workers))
	}

	// Create multi-phase job: 3 OCR pages, 1 LLM per OCR = 6 total units
	job := NewMultiPhaseJob(MultiPhaseJobConfig{
		OCRPages:  3,
		LLMPerOCR: 1,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Start worker pool
	go scheduler.RunWorkers(ctx, 2)

	// Submit job
	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Wait for completion
	for i := 0; i < 100; i++ {
		if job.Done() {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	if !job.Done() {
		ocr, llm, failed := job.Stats()
		t.Fatalf("job not done: ocr=%d/3 llm=%d/3 failed=%d", ocr, llm, failed)
	}

	// Verify both providers were used
	if ocrProvider.RequestCount() != 3 {
		t.Errorf("OCR provider got %d requests, want 3", ocrProvider.RequestCount())
	}
	if llmClient.RequestCount() != 3 {
		t.Errorf("LLM client got %d requests, want 3", llmClient.RequestCount())
	}
}

// TestScheduler_RoutesToCorrectWorkerType tests work unit routing.
func TestScheduler_RoutesToCorrectWorkerType(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{QueueSize: 100})

	// Add multiple workers of each type
	ocrProvider1 := providers.NewMockOCRProvider()
	ocrWorker1, _ := NewWorker(WorkerConfig{Name: "ocr-1", OCRProvider: ocrProvider1})
	scheduler.RegisterWorker(ocrWorker1)

	ocrProvider2 := providers.NewMockOCRProvider()
	ocrWorker2, _ := NewWorker(WorkerConfig{Name: "ocr-2", OCRProvider: ocrProvider2})
	scheduler.RegisterWorker(ocrWorker2)

	llmClient1 := providers.NewMockClient()
	llmWorker1, _ := NewWorker(WorkerConfig{Name: "llm-1", LLMClient: llmClient1, RPM: 6000})
	scheduler.RegisterWorker(llmWorker1)

	llmClient2 := providers.NewMockClient()
	llmWorker2, _ := NewWorker(WorkerConfig{Name: "llm-2", LLMClient: llmClient2, RPM: 6000})
	scheduler.RegisterWorker(llmWorker2)

	// Create job that targets specific providers
	job := NewMultiPhaseJob(MultiPhaseJobConfig{
		OCRPages:    2,
		LLMPerOCR:   1,
		OCRProvider: "ocr-2",
		LLMProvider: "llm-1",
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.RunWorkers(ctx, 4)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	// Wait for completion
	for i := 0; i < 100; i++ {
		if job.Done() {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	if !job.Done() {
		t.Fatal("job not done")
	}

	// OCR should only go to ocr-2
	if ocrProvider1.RequestCount() != 0 {
		t.Errorf("ocr-1 got %d requests, want 0", ocrProvider1.RequestCount())
	}
	if ocrProvider2.RequestCount() != 2 {
		t.Errorf("ocr-2 got %d requests, want 2", ocrProvider2.RequestCount())
	}

	// LLM should only go to llm-1
	if llmClient1.RequestCount() != 2 {
		t.Errorf("llm-1 got %d requests, want 2", llmClient1.RequestCount())
	}
	if llmClient2.RequestCount() != 0 {
		t.Errorf("llm-2 got %d requests, want 0", llmClient2.RequestCount())
	}
}

// MockDefraServer creates a test server that simulates DefraDB responses.
func MockDefraServer(t *testing.T) (*httptest.Server, *mockDefraState) {
	state := &mockDefraState{
		jobs: make(map[string]*Record),
	}

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		state.mu.Lock()
		defer state.mu.Unlock()

		w.Header().Set("Content-Type", "application/json")

		switch r.URL.Path {
		case "/health-check":
			w.WriteHeader(http.StatusOK)

		case "/api/v0/graphql":
			body := make([]byte, r.ContentLength)
			r.Body.Read(body)
			bodyStr := string(body)

			// Handle create mutation
			if strings.Contains(bodyStr, "create_Job") {
				state.jobCounter++
				id := "bae-job-" + string(rune('0'+state.jobCounter))
				state.jobs[id] = &Record{
					ID:        id,
					Status:    StatusQueued,
					CreatedAt: time.Now(),
				}
				json.NewEncoder(w).Encode(map[string]any{
					"data": map[string]any{
						"create_Job": []any{
							map[string]any{"_docID": id},
						},
					},
				})
				return
			}

			// Handle update mutation
			if strings.Contains(bodyStr, "update_Job") {
				if strings.Contains(bodyStr, `status: "running"`) {
					for _, job := range state.jobs {
						job.Status = StatusRunning
					}
				}
				if strings.Contains(bodyStr, `status: "completed"`) {
					for _, job := range state.jobs {
						job.Status = StatusCompleted
					}
				}
				json.NewEncoder(w).Encode(map[string]any{
					"data": map[string]any{
						"update_Job": []any{
							map[string]any{"_docID": "updated"},
						},
					},
				})
				return
			}

			// Handle list query
			if strings.Contains(bodyStr, "Job(") {
				jobs := make([]any, 0)
				for _, job := range state.jobs {
					jobs = append(jobs, map[string]any{
						"_docID":     job.ID,
						"job_type":   job.JobType,
						"status":     string(job.Status),
						"created_at": job.CreatedAt.Format(time.RFC3339),
					})
				}
				json.NewEncoder(w).Encode(map[string]any{
					"data": map[string]any{"Job": jobs},
				})
				return
			}

			// Default empty response
			json.NewEncoder(w).Encode(map[string]any{"data": map[string]any{}})

		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))

	return server, state
}

type mockDefraState struct {
	mu         sync.Mutex
	jobs       map[string]*Record
	jobCounter int
}

// TestScheduler_WithManager tests scheduler persistence via Manager.
func TestScheduler_WithManager(t *testing.T) {
	server, state := MockDefraServer(t)
	defer server.Close()

	defraClient := defra.NewClient(server.URL)
	manager := NewManager(defraClient, slog.Default())

	scheduler := NewScheduler(SchedulerConfig{
		Manager:   manager,
		Logger:    slog.Default(),
		QueueSize: 100,
	})

	ocrProvider := providers.NewMockOCRProvider()
	ocrWorker, _ := NewWorker(WorkerConfig{Name: "ocr", OCRProvider: ocrProvider})
	scheduler.RegisterWorker(ocrWorker)

	llmClient := providers.NewMockClient()
	llmWorker, _ := NewWorker(WorkerConfig{Name: "llm", LLMClient: llmClient, RPM: 6000})
	scheduler.RegisterWorker(llmWorker)

	job := NewMultiPhaseJob(MultiPhaseJobConfig{
		OCRPages:  2,
		LLMPerOCR: 1,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.RunWorkers(ctx, 2)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	for i := 0; i < 100; i++ {
		if job.Done() {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	state.mu.Lock()
	if len(state.jobs) == 0 {
		t.Error("no job record created in DefraDB")
	}
	state.mu.Unlock()
}

// TestScheduler_PartialFailure tests job continues despite some failures.
func TestScheduler_PartialFailure(t *testing.T) {
	scheduler := NewScheduler(SchedulerConfig{
		Logger:    slog.Default(),
		QueueSize: 100,
	})

	ocrProvider := providers.NewMockOCRProvider()
	ocrProvider.FailAfter = 1
	ocrWorker, _ := NewWorker(WorkerConfig{Name: "ocr", OCRProvider: ocrProvider})
	scheduler.RegisterWorker(ocrWorker)

	llmClient := providers.NewMockClient()
	llmWorker, _ := NewWorker(WorkerConfig{Name: "llm", LLMClient: llmClient, RPM: 6000})
	scheduler.RegisterWorker(llmWorker)

	job := NewMultiPhaseJob(MultiPhaseJobConfig{
		OCRPages:  3,
		LLMPerOCR: 1,
	})

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	go scheduler.RunWorkers(ctx, 2)

	if err := scheduler.Submit(ctx, job); err != nil {
		t.Fatalf("Submit() error = %v", err)
	}

	time.Sleep(2 * time.Second)

	ocr, llm, failed := job.Stats()

	if ocr != 1 {
		t.Errorf("ocr completed = %d, want 1", ocr)
	}
	if failed != 2 {
		t.Errorf("failed = %d, want 2", failed)
	}
	if llm != 1 {
		t.Errorf("llm completed = %d, want 1", llm)
	}
}
