package jobs

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
)

func withFastResumeBackoff(t *testing.T) {
	t.Helper()
	oldInitial, oldMax := resumeRetryInitialBackoff, resumeRetryMaxBackoff
	resumeRetryInitialBackoff = time.Millisecond
	resumeRetryMaxBackoff = 2 * time.Millisecond
	t.Cleanup(func() {
		resumeRetryInitialBackoff = oldInitial
		resumeRetryMaxBackoff = oldMax
	})
}

func newResumeTestScheduler(t *testing.T, recordStatus Status) (*Scheduler, func() []string) {
	t.Helper()
	var mu sync.Mutex
	var bodies []string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		bodyText := string(body)
		mu.Lock()
		bodies = append(bodies, bodyText)
		mu.Unlock()

		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(bodyText, "Job(") {
			requested := StatusRunning
			if strings.Contains(bodyText, string(StatusWaitingProvider)) {
				requested = StatusWaitingProvider
			}
			if requested == recordStatus {
				_, _ = fmt.Fprintf(w, `{"data":{"Job":[{"_docID":"job-1","job_type":"stub","book_id":"book-1","status":%q,"created_at":"2026-07-10T08:00:00Z","metadata":"{\"book_id\":\"book-1\"}"}]}}`, recordStatus)
				return
			}
			_, _ = w.Write([]byte(`{"data":{"Job":[]}}`))
			return
		}
		_, _ = w.Write([]byte(`{"data":{}}`))
	}))
	t.Cleanup(server.Close)

	s := NewScheduler(SchedulerConfig{
		Logger:  slog.Default(),
		Manager: NewManager(defra.NewClient(server.URL), slog.Default()),
	})
	return s, func() []string {
		mu.Lock()
		defer mu.Unlock()
		return append([]string(nil), bodies...)
	}
}

func TestResumeRetriesTransientFactoryFailureWithoutFailingBook(t *testing.T) {
	withFastResumeBackoff(t)
	s, requestBodies := newResumeTestScheduler(t, StatusRunning)

	attempts := 0
	var resumedJob *stubStartJob
	s.RegisterFactory("stub", func(context.Context, string, map[string]any) (Job, error) {
		attempts++
		if attempts == 1 {
			return nil, fmt.Errorf("Defra query: context deadline exceeded")
		}
		resumedJob = &stubStartJob{stubFailJob: stubFailJob{bookID: "book-1"}, done: true}
		return resumedJob, nil
	})

	resumed, err := s.Resume(context.Background())
	if err != nil {
		t.Fatalf("Resume error: %v", err)
	}
	if resumed != 1 || attempts != 2 {
		t.Fatalf("Resume = %d with %d factory attempts, want 1 and 2", resumed, attempts)
	}
	if resumedJob.failedReason != "" {
		t.Fatalf("transient resume failure marked book failed: %q", resumedJob.failedReason)
	}
	for _, body := range requestBodies() {
		if strings.Contains(body, `status: \"failed\"`) {
			t.Fatalf("transient resume failure wrote failed status: %s", body)
		}
	}
}

func TestResumeIncludesDurableWaitingProviderRecords(t *testing.T) {
	withFastResumeBackoff(t)
	s, _ := newResumeTestScheduler(t, StatusWaitingProvider)

	s.RegisterFactory("stub", func(context.Context, string, map[string]any) (Job, error) {
		return &stubStartJob{stubFailJob: stubFailJob{bookID: "book-1"}, done: true}, nil
	})

	resumed, err := s.Resume(context.Background())
	if err != nil {
		t.Fatalf("Resume error: %v", err)
	}
	if resumed != 1 {
		t.Fatalf("Resume = %d, want waiting_provider record resumed", resumed)
	}
}

func TestParseJobRecordIncludesLivenessFields(t *testing.T) {
	record, err := parseJobRecord(map[string]any{
		"_docID":           "job-1",
		"status":           string(StatusWaitingProvider),
		"status_reason":    "waiting for provider recovery: chandra-local",
		"heartbeat_at":     "2026-07-10T08:02:03.123Z",
		"last_progress_at": "2026-07-10T08:01:59Z",
	})
	if err != nil {
		t.Fatal(err)
	}
	if record.Status != StatusWaitingProvider || record.StatusReason == "" {
		t.Fatalf("status fields not parsed: %#v", record)
	}
	if record.HeartbeatAt == nil || record.LastProgressAt == nil {
		t.Fatalf("liveness fields not parsed: %#v", record)
	}
}

func TestProviderRecoveryRetriesTransientRuntimeStatusWrite(t *testing.T) {
	withFastResumeBackoff(t)
	var mu sync.Mutex
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		if !strings.Contains(string(body), "update_Job") {
			t.Fatalf("unexpected Defra request: %s", body)
		}
		mu.Lock()
		attempts++
		attempt := attempts
		mu.Unlock()
		w.Header().Set("Content-Type", "application/json")
		if attempt == 1 {
			_, _ = w.Write([]byte(`{"errors":[{"message":"transaction conflict. Please retry"}]}`))
			return
		}
		_, _ = w.Write([]byte(`{"data":{"update_Job":[{"_docID":"job-1"}]}}`))
	}))
	t.Cleanup(server.Close)

	s := NewScheduler(SchedulerConfig{
		Logger:  slog.Default(),
		Manager: NewManager(defra.NewClient(server.URL), slog.Default()),
	})
	s.mu.Lock()
	s.jobs["job-1"] = &stubStartJob{stubFailJob: stubFailJob{bookID: "book-1"}}
	s.waitingProviders["job-1"] = map[string]struct{}{"qwen-local": {}}
	s.mu.Unlock()

	s.providerWaitChanged("qwen-local", "job-1", false)

	mu.Lock()
	defer mu.Unlock()
	if attempts != 2 {
		t.Fatalf("runtime status update attempts = %d, want 2", attempts)
	}
}

func TestResumeRetriesTransientRunningStatusWrite(t *testing.T) {
	withFastResumeBackoff(t)
	var mu sync.Mutex
	runningUpdates := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		bodyText := string(body)
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(bodyText, "update_Job"):
			if strings.Contains(bodyText, `status: \"running\"`) {
				mu.Lock()
				runningUpdates++
				attempt := runningUpdates
				mu.Unlock()
				if attempt == 1 {
					_, _ = w.Write([]byte(`{"errors":[{"message":"transaction conflict. Please retry"}]}`))
					return
				}
			}
			_, _ = w.Write([]byte(`{"data":{"update_Job":[{"_docID":"job-1"}]}}`))
		case strings.Contains(bodyText, "Job(") && strings.Contains(bodyText, string(StatusWaitingProvider)):
			_, _ = w.Write([]byte(`{"data":{"Job":[]}}`))
		case strings.Contains(bodyText, "Job("):
			_, _ = w.Write([]byte(`{"data":{"Job":[{"_docID":"job-1","job_type":"stub","book_id":"book-1","status":"running","created_at":"2026-07-10T08:00:00Z","metadata":"{\"book_id\":\"book-1\"}"}]}}`))
		default:
			t.Fatalf("unexpected Defra request: %s", bodyText)
		}
	}))
	t.Cleanup(server.Close)

	s := NewScheduler(SchedulerConfig{
		Logger:  slog.Default(),
		Manager: NewManager(defra.NewClient(server.URL), slog.Default()),
	})
	s.RegisterFactory("stub", func(context.Context, string, map[string]any) (Job, error) {
		return &stubStartJob{stubFailJob: stubFailJob{bookID: "book-1"}, done: true}, nil
	})

	resumed, err := s.Resume(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if resumed != 1 {
		t.Fatalf("Resume = %d, want 1", resumed)
	}
	mu.Lock()
	defer mu.Unlock()
	if runningUpdates != 2 {
		t.Fatalf("running status update attempts = %d, want 2", runningUpdates)
	}
}
