package jobs

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

// stubPanicJob panics from OnComplete to exercise scheduler panic recovery.
type stubPanicJob struct{ stubFailJob }

func (j *stubPanicJob) OnComplete(context.Context, WorkResult) ([]WorkUnit, error) {
	panic("kaboom")
}

// stubFailJob implements Job + BookFailer and always errors from OnComplete.
type stubFailJob struct {
	bookID       string
	failedReason string
}

func (j *stubFailJob) ID() string                                { return "job-1" }
func (j *stubFailJob) SetRecordID(string)                        {}
func (j *stubFailJob) Type() string                              { return "stub" }
func (j *stubFailJob) Start(context.Context) ([]WorkUnit, error) { return nil, nil }
func (j *stubFailJob) OnComplete(context.Context, WorkResult) ([]WorkUnit, error) {
	return nil, fmt.Errorf("boom")
}
func (j *stubFailJob) Done() bool                                        { return false }
func (j *stubFailJob) Status(context.Context) (map[string]string, error) { return nil, nil }
func (j *stubFailJob) Progress() map[string]ProviderProgress             { return nil }
func (j *stubFailJob) MetricsFor() *WorkUnitMetrics                      { return nil }
func (j *stubFailJob) BookID() string                                    { return j.bookID }
func (j *stubFailJob) FailBook(_ context.Context, reason string)         { j.failedReason = reason }

type stubStartJob struct {
	stubFailJob
	units    []WorkUnit
	startErr error
	done     bool
}

func (j *stubStartJob) Start(context.Context) ([]WorkUnit, error) {
	return j.units, j.startErr
}

func (j *stubStartJob) Done() bool { return j.done }

type stubTransientStartJob struct {
	stubFailJob
	attempts int
	done     bool
}

func (j *stubTransientStartJob) Start(context.Context) ([]WorkUnit, error) {
	j.attempts++
	if j.attempts == 1 {
		return nil, fmt.Errorf("Defra load: context deadline exceeded")
	}
	j.done = true
	return nil, nil
}

func (j *stubTransientStartJob) Done() bool { return j.done }

type stubDrainedJob struct {
	stubFailJob
	reason string
}

func (j *stubDrainedJob) OnComplete(context.Context, WorkResult) ([]WorkUnit, error) {
	return nil, nil
}

func (j *stubDrainedJob) NoWorkFailure() string { return j.reason }

func TestHandleResultFailsBookOnJobError(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubFailJob{bookID: "book-1"}

	s.mu.Lock()
	s.jobs["job-1"] = stub
	s.pending["job-1"] = 1
	s.mu.Unlock()

	s.handleResult(context.Background(), workerResult{
		JobID:  "job-1",
		Unit:   &WorkUnit{ID: "u1"},
		Result: WorkResult{WorkUnitID: "u1", Success: false, Error: fmt.Errorf("boom")},
	})

	if stub.failedReason == "" {
		t.Fatal("expected FailBook to be called with a reason after OnComplete error")
	}
}

func TestHandleResultFailsBookWhenLastUnitDrainsWithoutDone(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubDrainedJob{
		stubFailJob: stubFailJob{bookID: "book-1"},
		reason:      "structure failed to build chapter skeleton: no linked ToC entries found",
	}

	s.mu.Lock()
	s.jobs["job-1"] = stub
	s.pending["job-1"] = 1
	s.mu.Unlock()

	s.handleResult(context.Background(), workerResult{
		JobID:  "job-1",
		Unit:   &WorkUnit{ID: "u1"},
		Result: WorkResult{WorkUnitID: "u1", Success: true},
	})

	if stub.failedReason != stub.reason {
		t.Fatalf("failedReason = %q, want %q", stub.failedReason, stub.reason)
	}
	if s.ActiveJobs() != 0 {
		t.Fatal("drained nonterminal job remained active")
	}
}

func TestStartJobAsyncFailsBookOnStartError(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubStartJob{
		stubFailJob: stubFailJob{bookID: "book-1"},
		startErr:    fmt.Errorf("start boom"),
	}

	s.mu.Lock()
	s.jobs["job-1"] = stub
	s.pending["job-1"] = 0
	s.mu.Unlock()

	s.startJobAsync(stub)

	if !strings.Contains(stub.failedReason, "start boom") {
		t.Fatalf("failedReason = %q, want start error", stub.failedReason)
	}
}

func TestStartJobAsyncRetriesTransientStartFailure(t *testing.T) {
	withFastResumeBackoff(t)
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubTransientStartJob{stubFailJob: stubFailJob{bookID: "book-1"}}
	s.mu.Lock()
	s.jobs[stub.ID()] = stub
	s.pending[stub.ID()] = 0
	s.mu.Unlock()

	s.startJobAsync(stub)

	if stub.attempts != 2 {
		t.Fatalf("Start attempts = %d, want 2", stub.attempts)
	}
	if stub.failedReason != "" {
		t.Fatalf("transient Start failed the book: %q", stub.failedReason)
	}
	if s.ActiveJobs() != 0 {
		t.Fatal("synchronously completed retried job remained active")
	}
}

func TestStartJobAsyncFailsBookOnNoWorkNotDone(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubStartJob{
		stubFailJob: stubFailJob{bookID: "book-1"},
		done:        false,
	}

	s.mu.Lock()
	s.jobs["job-1"] = stub
	s.pending["job-1"] = 0
	s.mu.Unlock()

	s.startJobAsync(stub)

	if !strings.Contains(stub.failedReason, "no work units") {
		t.Fatalf("failedReason = %q, want no-work failure", stub.failedReason)
	}
}

func TestStartJobAsyncUsesActionableNoWorkFailure(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubDrainedJob{
		stubFailJob: stubFailJob{bookID: "book-1"},
		reason:      "structure failed to build chapter skeleton: no linked ToC entries found",
	}
	s.mu.Lock()
	s.jobs[stub.ID()] = stub
	s.pending[stub.ID()] = 0
	s.mu.Unlock()

	s.startJobAsync(stub)

	if stub.failedReason != stub.reason {
		t.Fatalf("failedReason = %q, want actionable stage reason %q", stub.failedReason, stub.reason)
	}
}

func TestEmitFailureDoesNotBlockOnFullBuffer(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})

	// Saturate the results buffer. emitFailure is reachable from the sole
	// results consumer, so a blocking send here would deadlock the scheduler.
	for i := 0; i < cap(s.results); i++ {
		s.results <- workerResult{}
	}

	done := make(chan struct{})
	go func() {
		s.emitFailure(&WorkUnit{ID: "u1", JobID: "job-1"}, fmt.Errorf("no pool available"))
		close(done)
	}()

	select {
	case <-done:
		// Returned without blocking — correct.
	case <-time.After(2 * time.Second):
		t.Fatal("emitFailure blocked on a full results buffer (deadlock risk)")
	}
}

func TestHandleResultRecoversPanicAndFailsBook(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})
	stub := &stubPanicJob{stubFailJob{bookID: "book-1"}}

	s.mu.Lock()
	s.jobs["job-1"] = stub
	s.pending["job-1"] = 1
	s.mu.Unlock()

	// A panic in OnComplete must be recovered (no crash) and fail the book.
	s.handleResult(context.Background(), workerResult{
		JobID:  "job-1",
		Unit:   &WorkUnit{ID: "u1"},
		Result: WorkResult{WorkUnitID: "u1", Success: true},
	})

	if !strings.Contains(stub.failedReason, "panic") {
		t.Fatalf("failedReason = %q, want panic to be recovered and the book failed", stub.failedReason)
	}
}

func TestFailBookByRecordMarksJobAndBookFailed(t *testing.T) {
	var bodies []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		bodies = append(bodies, string(body))
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{}}`))
	}))
	defer server.Close()

	client := defra.NewClient(server.URL)
	s := NewScheduler(SchedulerConfig{
		Logger:  slog.Default(),
		Manager: NewManager(client, slog.Default()),
	})

	s.failBookByRecord(context.Background(), &Record{
		ID:     "job-1",
		BookID: "book-1",
	}, "resume failed: no factory registered for job type process-book")

	joined := strings.Join(bodies, "\n")
	if !strings.Contains(joined, "update_Job") {
		t.Fatalf("expected job record update, got bodies:\n%s", joined)
	}
	if !strings.Contains(joined, "update_Book") {
		t.Fatalf("expected book update, got bodies:\n%s", joined)
	}
	if !strings.Contains(joined, "status_reason") {
		t.Fatalf("expected status_reason in book update, got bodies:\n%s", joined)
	}
}
