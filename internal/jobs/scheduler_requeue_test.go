package jobs

import (
	"context"
	"errors"
	"log/slog"
	"testing"
	"time"
)

// stubCPUJob completes cleanly (OnComplete returns no error) and is Done, so a
// finished work unit drives the clean completion path.
type stubCPUJob struct {
	stubFailJob
	done bool
}

func (j *stubCPUJob) OnComplete(context.Context, WorkResult) ([]WorkUnit, error) { return nil, nil }
func (j *stubCPUJob) Done() bool                                                 { return j.done }

func TestEnqueueRequeuesOnQueueFull(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})

	pool := NewCPUWorkerPool(CPUWorkerPoolConfig{Name: "cpu", WorkerCount: 1, QueueSize: 1, Logger: slog.Default()})
	pool.init(s.results)
	if err := pool.Submit(&WorkUnit{ID: "filler", Type: WorkUnitTypeCPU}); err != nil {
		t.Fatalf("pre-fill Submit error: %v", err)
	}
	s.mu.Lock()
	s.cpuPool = pool
	s.pools["cpu"] = pool
	s.jobs["job-1"] = &stubFailJob{bookID: "book-1"}
	s.mu.Unlock()

	s.enqueueUnits("job-1", []WorkUnit{{ID: "u1", Type: WorkUnitTypeCPU}})

	select {
	case got := <-s.requeue:
		if got.ID != "u1" {
			t.Fatalf("requeued unit ID = %q, want u1", got.ID)
		}
	default:
		t.Fatal("expected unit on requeue channel; got none")
	}

	select {
	case wr := <-s.results:
		if errors.Is(wr.Result.Error, ErrWorkerQueueFull) {
			t.Fatal("queue-full should requeue, not emit a failure result")
		}
	default:
	}
}

// TestRequeueFullCycleRunsUnitAndDrainsPending exercises the whole backpressure
// path: a unit bounced by a full queue is parked, the requeue loop resubmits it,
// a worker runs it exactly once, and s.pending drains back to 0.
func TestRequeueFullCycleRunsUnitAndDrainsPending(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})

	executed := make(chan string, 4)
	pool := NewCPUWorkerPool(CPUWorkerPoolConfig{Name: "cpu", WorkerCount: 1, QueueSize: 1, Logger: slog.Default()})
	pool.RegisterHandler("run", func(ctx context.Context, req *CPUWorkRequest) (*CPUWorkResult, error) {
		executed <- req.Task
		return &CPUWorkResult{}, nil
	})
	pool.init(s.results)

	// Occupy the single slot with a filler that has NO registered handler, so it
	// fails silently (JobID "" => ignored) and never signals `executed`.
	if err := pool.Submit(&WorkUnit{ID: "filler", Type: WorkUnitTypeCPU, CPURequest: &CPUWorkRequest{Task: "missing"}}); err != nil {
		t.Fatalf("pre-fill Submit error: %v", err)
	}

	s.mu.Lock()
	s.cpuPool = pool
	s.pools["cpu"] = pool
	s.jobs["job-1"] = &stubCPUJob{stubFailJob: stubFailJob{bookID: "book-1"}, done: true}
	s.mu.Unlock()

	// Park the real unit while the queue is full.
	s.enqueueUnits("job-1", []WorkUnit{{ID: "u1", Type: WorkUnitTypeCPU, CPURequest: &CPUWorkRequest{Task: "run"}}})

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	go s.Start(ctx)

	select {
	case task := <-executed:
		if task != "run" {
			t.Fatalf("executed task = %q, want run", task)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("timed out waiting for the requeued unit to run")
	}

	drained := false
	for i := 0; i < 300; i++ {
		s.mu.Lock()
		_, present := s.jobs["job-1"]
		pending := s.pending["job-1"]
		s.mu.Unlock()
		if !present && pending == 0 {
			drained = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !drained {
		t.Fatal("expected job-1 to complete: pending drained to 0 and job removed")
	}

	// The unit must have run exactly once (no duplicate resubmit).
	select {
	case extra := <-executed:
		t.Fatalf("requeued unit ran more than once (extra=%q)", extra)
	case <-time.After(200 * time.Millisecond):
	}
}
