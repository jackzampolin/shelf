# Pipeline Terminal States & Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `process_book` pipeline never leave a book silently stuck in `processing`: every job death drives the book to a terminal `failed` state with a reason, a reconciler catches strays, a scoreboard endpoint reports the fleet, deterministic errors fail fast, transient ones retry, over-large agent prompts are bounded, and CPU-queue-full becomes backpressure instead of a fatal error.

**Architecture:** Five independent, independently-shippable task groups. Group 1 (state machine) is the keystone — it converts the observed "stuck in processing, 0 running jobs" dead-end into a clean terminal `failed`. Group 2 (scoreboard) is the daily-triage surface for the wipe-and-rerun loop. Groups 3–5 (token caps, retry classification, CPU backpressure) reduce the failure count each run. Book status is a plain `String` field on the `Book` collection written today only at `Start` (→`processing`) and `CheckCompletion` (→`complete`); this plan adds `failed` writers on the failure paths plus a `status_reason`.

**Tech Stack:** Go, DefraDB (GraphQL), Cobra CLI, `svcctx` context-based DI, `slog`.

## Global Constraints

- **DefraDB has NO NonNull fields** — declare schema fields as `field: String`, never `String!`.
- **Cost/compute awareness** — never run commands that spawn real LLM/OCR jobs (`shelf serve` + job submit, `shelf api jobs start`). Tests use mocks / in-memory stores only.
- **Book status string values are a shared contract** across packages: `"ingested"`, `"processing"`, `"complete"`, `"failed"`. The typed `BookStatus` constants live in `internal/jobs/process_book/job/types.go`; code in package `jobs` (scheduler/reconciler) that cannot import the job package uses the string literals verbatim.
- **Commit trailer** on every commit:
  ```
  🤖 Generated with [Claude Code](https://claude.com/claude-code)

  Co-Authored-By: Claude <noreply@anthropic.com>
  ```
- **Follow existing patterns** — endpoints implement the `api.Endpoint` interface and register in both `endpoints.All()` and `cmd/shelf/api.go`; DB writes go through `defra.Client`/`defra.Sink`/`BookState` persist helpers; match neighboring test style.
- **Operating model** — the maintainer wipes the DB and re-runs all 25 books daily. Optimize for a clean per-run scoreboard and terminal states; resume/reset recovery UX is explicitly out of scope.

---

## File Structure

**Group 1 — Terminal state machine**
- Modify `internal/schema/schemas/book.graphql` — add `status_reason: String`.
- Modify `internal/jobs/process_book/job/types.go` — add `BookStatusFailed`.
- Modify `internal/jobs/common/state_persist_book.go` — add `PersistBookStatusWithReason`; clear `status_reason` in `PersistBookStatus`/`PersistBookStatusAsync`.
- Modify `internal/jobs/common/persist.go` — clear `status_reason` in the exported deprecated `common.PersistBookStatus` helper too.
- Modify `internal/jobs/process_book/job/job.go` — add `FailBook` method.
- Modify `internal/jobs/job.go` — add `BookFailer` interface.
- Modify `internal/jobs/scheduler.go` — `failBookForJob` + `failBookByRecord` helpers; wire into `handleResult` and `startJobAsync`; start reconciler loop in `Start`.
- Modify `internal/jobs/scheduler_submit.go` — wire `failBookForJob` into `startJobAsync` and `Resume` failure branches; wire `failBookByRecord` into the two `Resume` factory-failure branches.
- Create `internal/jobs/scheduler_reconcile.go` — reconciler + pure `bookIsStranded`.
- Tests: `internal/jobs/common/state_persist_book_reason_test.go`, `internal/jobs/process_book/job/fail_book_test.go`, `internal/jobs/scheduler_failbook_test.go`, `internal/jobs/scheduler_reconcile_test.go`.

**Group 2 — Scoreboard**
- Create `internal/server/endpoints/run_summary.go`.
- Modify `internal/server/endpoints/registry.go` — register `&RunSummaryEndpoint{}`.
- Modify `cmd/shelf/api.go` — add the CLI command.
- Test: `internal/server/endpoints/run_summary_test.go`.

**Group 3 — Token caps**
- Modify `internal/agents/chapter_finder/tools/get_page_ocr.go` — cap `ocr_text`.
- Modify `internal/agents/chapter_finder/tools/grep_text.go` — cap match count.
- Tests: `internal/agents/chapter_finder/tools/get_page_ocr_test.go`, `internal/agents/chapter_finder/tools/grep_text_test.go`.

**Group 4 — Retry classification**
- Create `internal/jobs/error_class.go` — exported `IsRetriableError`.
- Modify `internal/jobs/provider_pool.go` — delegate to `IsRetriableError`.
- Modify `internal/jobs/process_book/job/job.go` — fail fast on non-retriable book-op errors.
- Tests: `internal/jobs/error_class_test.go`, additions to `internal/jobs/process_book/job/book_op_retry_test.go`.

**Group 5 — CPU backpressure**
- Modify `internal/jobs/scheduler.go` — `requeue` channel + `requeueLoop` + `emitFailure`.
- Modify `internal/jobs/scheduler_routing.go` — requeue on `ErrWorkerQueueFull`.
- Test: `internal/jobs/scheduler_requeue_test.go`.

---

# GROUP 1 — Terminal `failed` state + failure propagation + reconciler

### Task 1: Book `status_reason` field, `BookStatusFailed`, and `PersistBookStatusWithReason`

**Files:**
- Modify: `internal/schema/schemas/book.graphql` (Processing state block, ~line 26)
- Modify: `internal/jobs/process_book/job/types.go:17-21`
- Modify: `internal/jobs/common/state_persist_book.go:38-66`
- Modify: `internal/jobs/common/persist.go:141-152`
- Test: `internal/jobs/common/state_persist_book_reason_test.go` (create)

**Interfaces:**
- Produces: `(*common.BookState).PersistBookStatusWithReason(ctx context.Context, status, reason string) (string, error)`; `job.BookStatusFailed BookStatus = "failed"`; DB field `Book.status_reason: String`.

- [ ] **Step 1: Write the failing test**

Create `internal/jobs/common/state_persist_book_reason_test.go`:

```go
package common

import (
	"context"
	"testing"
)

func TestPersistBookStatusWithReason(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	b := NewBookState("book-1")
	b.Store = store

	if _, err := b.PersistBookStatusWithReason(context.Background(), "failed", "finalize context limit"); err != nil {
		t.Fatalf("PersistBookStatusWithReason error: %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != "failed" {
		t.Fatalf("status = %v, want failed", doc["status"])
	}
	if doc["status_reason"] != "finalize context limit" {
		t.Fatalf("status_reason = %v, want 'finalize context limit'", doc["status_reason"])
	}
}

func TestPersistBookStatusClearsStaleReason(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{"status": "failed", "status_reason": "old failure"})

	b := NewBookState("book-1")
	b.Store = store

	// A later successful transition must clear the stale reason.
	if _, err := b.PersistBookStatus(context.Background(), "complete"); err != nil {
		t.Fatalf("PersistBookStatus error: %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != "complete" {
		t.Fatalf("status = %v, want complete", doc["status"])
	}
	if doc["status_reason"] != "" {
		t.Fatalf("status_reason = %v, want empty (cleared)", doc["status_reason"])
	}
}

func TestPersistBookStatusHelperClearsStaleReason(t *testing.T) {
	store := NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{"status": "failed", "status_reason": "old failure"})

	b := NewBookState("book-1")
	b.Store = store

	// The exported package helper is deprecated but still part of the package
	// surface; it must not preserve stale failure reasons either.
	if _, err := PersistBookStatus(context.Background(), b, "processing"); err != nil {
		t.Fatalf("PersistBookStatus helper error: %v", err)
	}

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != "processing" {
		t.Fatalf("status = %v, want processing", doc["status"])
	}
	if doc["status_reason"] != "" {
		t.Fatalf("status_reason = %v, want empty (cleared)", doc["status_reason"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/common/ -run 'TestPersistBookStatusWithReason|TestPersistBookStatusClearsStaleReason|TestPersistBookStatusHelperClearsStaleReason' -v`
Expected: FAIL — `PersistBookStatusWithReason undefined` and the clear-reason tests fail (existing status writers write only `status`).

- [ ] **Step 3: Add the schema field**

In `internal/schema/schemas/book.graphql`, under the `# Processing state` comment (right after `status: String` is fine too), add:

```graphql
    status_reason: String
```

- [ ] **Step 4: Add the `BookStatusFailed` constant**

In `internal/jobs/process_book/job/types.go`, extend the const block:

```go
const (
	BookStatusIngested   BookStatus = "ingested"
	BookStatusProcessing BookStatus = "processing"
	BookStatusComplete   BookStatus = "complete"
	BookStatusFailed     BookStatus = "failed"
)
```

- [ ] **Step 5: Add `PersistBookStatusWithReason`**

In `internal/jobs/common/state_persist_book.go`, add after `PersistBookStatus` (after line 66):

```go
// PersistBookStatusWithReason updates book status plus a human-readable reason
// in DB and memory. Used for terminal failure so the scoreboard can explain why.
func (b *BookState) PersistBookStatusWithReason(ctx context.Context, status, reason string) (string, error) {
	store := b.getStore(ctx)
	if store == nil {
		return "", fmt.Errorf("no store available")
	}

	result, err := store.SendSync(ctx, defra.WriteOp{
		Collection: "Book",
		DocID:      b.BookID,
		Document: map[string]any{
			"status":        status,
			"status_reason": reason,
		},
		Op: defra.OpUpdate,
	})
	if err != nil {
		return "", err
	}

	b.mu.Lock()
	b.trackCIDLocked("Book", b.BookID, result.CID)
	b.bookCID = result.CID
	b.mu.Unlock()

	return result.CID, nil
}
```

- [ ] **Step 5b: Clear `status_reason` on non-failure status writes**

So a stale failure reason never sticks to a book that later succeeds, add `"status_reason": ""` to every non-failure status writer: BOTH existing writers in `internal/jobs/common/state_persist_book.go` plus the exported deprecated helper in `internal/jobs/common/persist.go`.

In `PersistBookStatus` (sync, ~line 51):

```go
		Document: map[string]any{
			"status":        status,
			"status_reason": "",
		},
```

In `PersistBookStatusAsync` (~line 80):

```go
		Document: map[string]any{
			"status":        status,
			"status_reason": "",
		},
```

(`PersistBookStatusWithReason` is the only writer that sets a non-empty reason.)

In `internal/jobs/common/persist.go`, update the exported deprecated helper too:

```go
		Document: map[string]any{
			"status":        status,
			"status_reason": "",
		},
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `go test ./internal/jobs/common/ -run 'TestPersistBookStatusWithReason|TestPersistBookStatusClearsStaleReason|TestPersistBookStatusHelperClearsStaleReason' -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add internal/schema/schemas/book.graphql internal/jobs/process_book/job/types.go internal/jobs/common/state_persist_book.go internal/jobs/common/persist.go internal/jobs/common/state_persist_book_reason_test.go
git commit -m "feat: add Book.status_reason + failed status writer"
```

---

### Task 2: `Job.FailBook` + `jobs.BookFailer` interface

**Files:**
- Modify: `internal/jobs/job.go` (near the `BookIDProvider` interface)
- Modify: `internal/jobs/process_book/job/job.go` (add method near end of file)
- Test: `internal/jobs/process_book/job/fail_book_test.go` (create)

**Interfaces:**
- Consumes: `(*common.BookState).PersistBookStatusWithReason` (Task 1); `job.BookStatusFailed` (Task 1).
- Produces: `jobs.BookFailer` interface with `FailBook(ctx context.Context, reason string)`; `(*job.Job).FailBook(ctx, reason)`.

- [ ] **Step 1: Write the failing test**

Create `internal/jobs/process_book/job/fail_book_test.go`:

```go
package job

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestFailBookPersistsFailedStatusWithReason(t *testing.T) {
	store := common.NewMemoryStateStore()
	store.SetDoc("Book", "book-1", map[string]any{})

	book := common.NewBookState("book-1")
	book.Store = store
	j := NewFromLoadResult(&common.LoadBookResult{Book: book})

	j.FailBook(context.Background(), "work unit failed (finalize_discover): context length")

	doc := store.GetDoc("Book", "book-1")
	if doc["status"] != string(BookStatusFailed) {
		t.Fatalf("status = %v, want %v", doc["status"], BookStatusFailed)
	}
	if doc["status_reason"] != "work unit failed (finalize_discover): context length" {
		t.Fatalf("status_reason = %v", doc["status_reason"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/process_book/job/ -run TestFailBookPersistsFailedStatusWithReason -v`
Expected: FAIL — `j.FailBook undefined`.

- [ ] **Step 3: Add the `BookFailer` interface**

In `internal/jobs/job.go`, immediately after the `BookIDProvider` interface definition, add:

```go
// BookFailer is an optional interface for jobs that can mark their book
// terminally failed with a reason. The scheduler calls this when a job dies so
// the book does not remain stuck in "processing".
type BookFailer interface {
	FailBook(ctx context.Context, reason string)
}
```

(If `BookIDProvider` is not in `job.go`, place `BookFailer` next to wherever `BookIDProvider` is declared — `grep -rn "BookIDProvider interface" internal/jobs/`.)

- [ ] **Step 4: Add the `FailBook` method**

In `internal/jobs/process_book/job/job.go`, add near the other `Job` methods (e.g. after `createRetryUnit`):

```go
// FailBook marks the book terminally failed with a reason. Implements
// jobs.BookFailer; called by the scheduler when this job dies so the book does
// not stay stuck in "processing".
func (j *Job) FailBook(ctx context.Context, reason string) {
	if j.Book == nil {
		return
	}
	if _, err := j.Book.PersistBookStatusWithReason(ctx, string(BookStatusFailed), reason); err != nil {
		if logger := svcctx.LoggerFrom(ctx); logger != nil {
			logger.Warn("failed to persist book failed status",
				"book_id", j.Book.BookID, "error", err)
		}
	}
}
```

(`svcctx` is already imported in `job.go`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `go test ./internal/jobs/process_book/job/ -run TestFailBookPersistsFailedStatusWithReason -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/jobs/job.go internal/jobs/process_book/job/job.go internal/jobs/process_book/job/fail_book_test.go
git commit -m "feat: add BookFailer interface and Job.FailBook"
```

---

### Task 3: Scheduler propagates job death to book status

Covers **every** scheduler path that can kill a job after `process_book.Start` has set the book to `processing`: `handleResult` (Task 3 core), `startJobAsync` (the primary submit path), and all four `Resume` failure branches (`job.Start` error, no-work-units, factory-missing, factory-recreate-failure). The two factory branches have no `Job` object, so they use a record-based fallback that also marks the stale `running` record `failed` (otherwise the reconciler, which correctly skips `running` records, would never catch them).

**Files:**
- Modify: `internal/jobs/scheduler.go` (add `failBookForJob` + `failBookByRecord`; call `failBookForJob` in `handleResult`)
- Modify: `internal/jobs/scheduler_submit.go` (call `failBookForJob` in `startJobAsync`'s two failure branches + `Resume`'s `job.Start`/no-work branches; call `failBookByRecord` in `Resume`'s two factory-failure branches)
- Test: `internal/jobs/scheduler_failbook_test.go` (create)

**Interfaces:**
- Consumes: `jobs.BookFailer` (Task 2); `(*Scheduler).injectServices`, `(*Scheduler).handleResult`; `(*Manager).UpdateStatus`; `s.manager.defra.Update`; `Record.BookID`.
- Produces: `(*Scheduler).failBookForJob(ctx context.Context, job Job, reason string)`; `(*Scheduler).failBookByRecord(ctx context.Context, record *Record, reason string)`.

- [ ] **Step 1: Write the failing test**

Create `internal/jobs/scheduler_failbook_test.go`:

```go
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

	"github.com/jackzampolin/shelf/internal/defra"
)

// stubFailJob implements Job + BookFailer and always errors from OnComplete.
type stubFailJob struct {
	bookID       string
	failedReason string
}

func (j *stubFailJob) ID() string                 { return "job-1" }
func (j *stubFailJob) SetRecordID(string)          {}
func (j *stubFailJob) Type() string                { return "stub" }
func (j *stubFailJob) Start(context.Context) ([]WorkUnit, error) { return nil, nil }
func (j *stubFailJob) OnComplete(context.Context, WorkResult) ([]WorkUnit, error) {
	return nil, fmt.Errorf("boom")
}
func (j *stubFailJob) Done() bool                                   { return false }
func (j *stubFailJob) Status(context.Context) (map[string]string, error) { return nil, nil }
func (j *stubFailJob) Progress() map[string]ProviderProgress        { return nil }
func (j *stubFailJob) MetricsFor() *WorkUnitMetrics                 { return nil }
func (j *stubFailJob) BookID() string                               { return j.bookID }
func (j *stubFailJob) FailBook(_ context.Context, reason string)    { j.failedReason = reason }

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/ -run 'TestHandleResultFailsBookOnJobError|TestStartJobAsyncFailsBook|TestFailBookByRecordMarksJobAndBookFailed' -v`
Expected: FAIL — `stub.failedReason` empty (scheduler does not yet call `FailBook`), `startJobAsync` does not yet fail the book, and `failBookByRecord` does not exist.

(If it fails to compile because `NewScheduler` does not initialize `s.jobs`/`s.pending`, verify field names with `grep -n "jobs\|pending" internal/jobs/scheduler.go` and adjust the test's direct map writes — the maps are initialized in `NewScheduler`.)

- [ ] **Step 3: Add `failBookForJob` and call it in `handleResult`**

In `internal/jobs/scheduler.go`, add the helper:

```go
// failBookForJob marks a job's book terminally failed if the job supports it.
func (s *Scheduler) failBookForJob(ctx context.Context, job Job, reason string) {
	if bf, ok := job.(BookFailer); ok {
		bf.FailBook(ctx, reason)
	}
}

// failBookByRecord marks a book failed when no live Job exists (e.g. a Resume
// factory failure). It also marks the job record failed so the stale "running"
// record does not defeat the reconciler. "failed" must match job.BookStatusFailed
// (see Global Constraints). Do not import svcctx in package jobs: svcctx already
// imports jobs, so that would create an import cycle.
func (s *Scheduler) failBookByRecord(ctx context.Context, record *Record, reason string) {
	if record == nil {
		return
	}
	if s.manager != nil && record.ID != "" {
		if err := s.manager.UpdateStatus(ctx, record.ID, StatusFailed, reason); err != nil {
			s.logger.Warn("failed to mark job record failed", "job_id", record.ID, "error", err)
		}
	}
	if record.BookID == "" {
		return
	}
	if s.manager == nil || s.manager.defra == nil {
		return
	}
	if err := s.manager.defra.Update(ctx, "Book", record.BookID, map[string]any{
		"status":        "failed",
		"status_reason": reason,
	}); err != nil {
		s.logger.Warn("failed to mark book failed by record", "book_id", record.BookID, "error", err)
	}
}
```

(No new `svcctx` import belongs in `internal/jobs`; use the manager's DefraDB client because this code is in package `jobs` and can access `s.manager.defra`.)

Then in `handleResult`, inside the `if err != nil` branch after `job.OnComplete`, add the `failBookForJob` call (using the already-built `enrichedCtx`):

```go
	newUnits, err := job.OnComplete(enrichedCtx, wr.Result)
	if err != nil {
		s.logger.Error("job OnComplete failed", "job_id", wr.JobID, "error", err)
		s.failBookForJob(enrichedCtx, job, err.Error())
		s.removeJob(wr.JobID)
		if s.manager != nil {
			if updateErr := s.manager.UpdateStatus(ctx, wr.JobID, StatusFailed, err.Error()); updateErr != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", updateErr)
			}
		}
		return
	}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/jobs/ -run 'TestHandleResultFailsBookOnJobError|TestStartJobAsyncFailsBook|TestFailBookByRecordMarksJobAndBookFailed' -v`
Expected: PASS.

- [ ] **Step 5: Wire `startJobAsync` failure branches**

In `internal/jobs/scheduler_submit.go`, `startJobAsync` already has an injected `ctx` (from `s.injectServices`). Add `s.failBookForJob(ctx, job, err.Error())` before `s.removeJob(...)` in its two failure branches.

The `job.Start` error branch (~line 74):

```go
	units, err := job.Start(ctx)
	if err != nil {
		jobID := job.ID()
		s.logger.Error("job start failed", "job_id", jobID, "error", err)
		s.failBookForJob(ctx, job, err.Error())
		s.removeJob(jobID)

		// Mark as failed in DefraDB
		if s.manager != nil && jobID != "" {
			s.manager.UpdateStatus(ctx, jobID, StatusFailed, err.Error())
		}
		return
	}
```

The "job started with no work units and is not done" branch (~line 102):

```go
	if len(units) == 0 {
		jobID := job.ID()
		err := fmt.Errorf("job started with no work units and is not done")
		s.logger.Error("job start produced no work", "job_id", jobID, "type", job.Type())
		s.failBookForJob(ctx, job, err.Error())
		s.removeJob(jobID)
		if s.manager != nil && jobID != "" {
			if updateErr := s.manager.UpdateStatus(ctx, jobID, StatusFailed, err.Error()); updateErr != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", updateErr)
			}
		}
		return
	}
```

- [ ] **Step 6: Wire the four `Resume` failure branches**

In `internal/jobs/scheduler_submit.go`, in `Resume`:

The factory-missing branch (~line 170) — no `Job` exists yet, so use `failBookByRecord` (which also flips the stale `running` record to `failed`):

```go
		if !ok {
			s.logger.Warn("no factory for job type, cannot resume",
				"job_id", record.ID, "type", record.JobType)
			s.failBookByRecord(ctx, record, "resume failed: no factory registered for job type "+record.JobType)
			continue
		}
```

The factory-recreate-failure branch (~line 181):

```go
		job, err := factory(enrichedCtx, record.ID, record.Metadata)
		if err != nil {
			s.logger.Error("failed to recreate job",
				"job_id", record.ID, "error", err)
			s.failBookByRecord(enrichedCtx, record, "resume failed to recreate job: "+err.Error())
			continue
		}
```

The `job.Start` error branch (~line 200) and the no-work branch — use `failBookForJob` (the `Job` exists):

```go
		units, err := job.Start(enrichedCtx)
		if err != nil {
			s.logger.Error("failed to resume job",
				"job_id", record.ID, "error", err)
			s.failBookForJob(enrichedCtx, job, err.Error())
			s.removeJob(job.ID())
			s.manager.UpdateStatus(enrichedCtx, record.ID, StatusFailed, err.Error())
			continue
		}
```

```go
		if len(units) == 0 {
			err := fmt.Errorf("resumed job produced no work units and is not done")
			s.logger.Error("failed to resume job",
				"job_id", record.ID,
				"type", record.JobType,
				"error", err)
			s.failBookForJob(enrichedCtx, job, err.Error())
			s.removeJob(job.ID())
			if updateErr := s.manager.UpdateStatus(enrichedCtx, record.ID, StatusFailed, err.Error()); updateErr != nil {
				s.logger.Warn("failed to update job status in DefraDB", "error", updateErr)
			}
			continue
		}
```

- [ ] **Step 7: Run the jobs package tests**

Run: `go test ./internal/jobs/ -run 'TestHandleResult|TestStartJobAsync|TestFailBookByRecord|TestResume|TestScheduler' -v`
Expected: PASS (no regressions).

- [ ] **Step 8: Commit**

```bash
git add internal/jobs/scheduler.go internal/jobs/scheduler_submit.go internal/jobs/scheduler_failbook_test.go
git commit -m "feat: propagate job death to book failed status across all scheduler paths"
```

---

### Task 4: Stalled-book reconciler

**Files:**
- Create: `internal/jobs/scheduler_reconcile.go`
- Modify: `internal/jobs/scheduler.go` (start `reconcileLoop` in `Start`)
- Test: `internal/jobs/scheduler_reconcile_test.go` (create)

**Interfaces:**
- Consumes: `(*Scheduler).GetJobByBookID`, `(*Manager).List`, `ListFilter{BookID}`, `s.manager.defra.Query/Update`.
- Produces: pure `bookIsStranded(hasActiveInMemoryJob bool, records []*Record) bool`; `(*Scheduler).reconcileStalledBooks(ctx)`; `(*Scheduler).reconcileLoop(ctx)`.

- [ ] **Step 1: Write the failing test (pure decision function)**

Create `internal/jobs/scheduler_reconcile_test.go`:

```go
package jobs

import "testing"

func TestBookIsStranded(t *testing.T) {
	cases := []struct {
		name     string
		active   bool
		records  []*Record
		stranded bool
	}{
		{"active in-memory job", true, []*Record{{Status: StatusFailed}}, false},
		{"failed only, no active", false, []*Record{{Status: StatusFailed}}, true},
		{"running record present", false, []*Record{{Status: StatusRunning}, {Status: StatusFailed}}, false},
		{"queued record present", false, []*Record{{Status: StatusQueued}}, false},
		{"completed only", false, []*Record{{Status: StatusCompleted}}, false},
		{"no records", false, nil, false},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			if got := bookIsStranded(tc.active, tc.records); got != tc.stranded {
				t.Fatalf("bookIsStranded = %v, want %v", got, tc.stranded)
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/ -run TestBookIsStranded -v`
Expected: FAIL — `bookIsStranded undefined`.

- [ ] **Step 3: Create the reconciler file**

Create `internal/jobs/scheduler_reconcile.go`:

```go
package jobs

import (
	"context"
	"time"
)

// reconcileInterval is how often the scheduler scans for stalled books.
const reconcileInterval = 2 * time.Minute

// bookIsStranded reports whether a book currently in "processing" is stranded:
// it has no active in-memory job, no queued/running job record, and at least
// one failed job record. This is the exact "processing with 0 running jobs +
// a failed job" signature from the overnight run.
func bookIsStranded(hasActiveInMemoryJob bool, records []*Record) bool {
	if hasActiveInMemoryJob {
		return false
	}
	hasFailed := false
	for _, r := range records {
		switch r.Status {
		case StatusRunning, StatusQueued:
			return false
		case StatusFailed:
			hasFailed = true
		}
	}
	return hasFailed
}

// reconcileLoop periodically marks stalled books failed. Flag-only: it never
// resubmits work.
func (s *Scheduler) reconcileLoop(ctx context.Context) {
	ticker := time.NewTicker(reconcileInterval)
	defer ticker.Stop()
	for {
		select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				s.reconcileStalledBooks(ctx)
			}
		}
	}

// reconcileStalledBooks queries books in "processing", and for any that are
// stranded, marks them "failed" with a reason. Requires a DefraDB client and a
// job manager/scheduler; a no-op otherwise. Do not import svcctx in package jobs:
// svcctx imports jobs, so that would create an import cycle.
func (s *Scheduler) reconcileStalledBooks(ctx context.Context) {
	if s.manager == nil || s.manager.defra == nil {
		return
	}
	client := s.manager.defra

	resp, err := client.Query(ctx, `{ Book(filter: {status: {_eq: "processing"}}) { _docID } }`)
	if err != nil {
		s.logger.Warn("reconciler: failed to query processing books", "error", err)
		return
	}
	if msg := resp.Error(); msg != "" {
		s.logger.Warn("reconciler: query returned error", "error", msg)
		return
	}

	data, _ := resp.Data["Book"].([]any)
	for _, item := range data {
		m, ok := item.(map[string]any)
		if !ok {
			continue
		}
		docID, _ := m["_docID"].(string)
		if docID == "" {
			continue
		}

		hasActive := s.GetJobByBookID(docID) != nil
		records, err := s.manager.List(ctx, ListFilter{BookID: docID})
		if err != nil {
			s.logger.Warn("reconciler: failed to list jobs for book", "book_id", docID, "error", err)
			continue
		}
		if !bookIsStranded(hasActive, records) {
			continue
		}

		// "failed" must match job.BookStatusFailed (see Global Constraints).
		reason := "stalled: processing with no active job and a failed job record (reconciler)"
		if err := client.Update(ctx, "Book", docID, map[string]any{
			"status":        "failed",
			"status_reason": reason,
		}); err != nil {
			s.logger.Warn("reconciler: failed to mark book failed", "book_id", docID, "error", err)
			continue
		}
		s.logger.Info("reconciler marked stalled book failed", "book_id", docID)
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/jobs/ -run TestBookIsStranded -v`
Expected: PASS.

- [ ] **Step 5: Start the reconciler loop in `Start`**

In `internal/jobs/scheduler.go`, in `Start`, after the pool-start loop and `s.mu.Unlock()` (just before `s.logger.Info("scheduler started", ...)`), add:

```go
	// Periodically catch books stranded in "processing" (flag-only).
	go s.reconcileLoop(ctx)
```

- [ ] **Step 6: Verify the package builds and tests pass**

Run: `go build ./internal/jobs/... && go test ./internal/jobs/ -run 'TestBookIsStranded|TestScheduler' -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add internal/jobs/scheduler_reconcile.go internal/jobs/scheduler.go internal/jobs/scheduler_reconcile_test.go
git commit -m "feat: add stalled-book reconciler (flag-only)"
```

---

# GROUP 2 — Run-summary scoreboard endpoint

### Task 5: `GET /api/run/summary` + `shelf api run-summary`

**Files:**
- Create: `internal/server/endpoints/run_summary.go`
- Modify: `internal/server/endpoints/registry.go` (add to `All()`)
- Modify: `cmd/shelf/api.go` (add `apiCmd.AddCommand(...)`)
- Test: `internal/server/endpoints/run_summary_test.go` (create)

**Interfaces:**
- Consumes: `api.Endpoint`, `svcctx.DefraClientFrom`, `svcctx.JobManagerFrom`, `(*jobs.Manager).List`, `jobs.ListFilter{JobType}`, `jobs.Record`, `api.NewClient`, `api.Output`.
- Produces: `RunSummaryEndpoint`; response types `RunSummaryResponse`/`BookSummary`; pure `recoveryHint(status, statusReason, latestError string) string`.

- [ ] **Step 1: Write the failing test (pure hint function)**

Create `internal/server/endpoints/run_summary_test.go`:

```go
package endpoints

import (
	"strings"
	"testing"
)

func TestRecoveryHint(t *testing.T) {
	cases := []struct {
		name        string
		status      string
		reason      string
		latestError string
		wantSubstr  string
	}{
		{"context length", "failed", "", "OpenRouter error (status 400): maximum context length is 65536", "context"},
		{"endpoint down", "failed", "", `dial tcp 100.86.62.91:8000: connect: connection refused`, "endpoint"},
		{"no work units", "failed", "resumed job produced no work units and is not done", "", "re-run"},
		{"queue full", "failed", "", "work unit failed (extract): worker queue full: cpu", "queue"},
		{"still processing", "processing", "", "", "active job"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := recoveryHint(tc.status, tc.reason, tc.latestError)
			if !strings.Contains(strings.ToLower(got), tc.wantSubstr) {
				t.Fatalf("recoveryHint = %q, want substring %q", got, tc.wantSubstr)
			}
		})
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/server/endpoints/ -run TestRecoveryHint -v`
Expected: FAIL — `recoveryHint undefined`.

- [ ] **Step 3: Create the endpoint**

Create `internal/server/endpoints/run_summary.go`:

```go
package endpoints

import (
	"net/http"
	"sort"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// RunSummaryResponse is the fleet scoreboard: counts by bucket + per-book detail.
type RunSummaryResponse struct {
	Total     int            `json:"total"`
	Counts    map[string]int `json:"counts"`
	Books     []BookSummary  `json:"books"`
}

// BookSummary is one book's terminal/processing state and recovery hint.
type BookSummary struct {
	ID           string `json:"id"`
	Title        string `json:"title"`
	Status       string `json:"status"`
	StatusReason string `json:"status_reason,omitempty"`
	LatestError  string `json:"latest_error,omitempty"`
	RecoveryHint string `json:"recovery_hint,omitempty"`
}

// RunSummaryEndpoint handles GET /api/run/summary.
type RunSummaryEndpoint struct{}

func (e *RunSummaryEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/run/summary", e.handler
}

func (e *RunSummaryEndpoint) RequiresInit() bool { return true }

// recoveryHint maps an observed failure signature to the concrete next action.
func recoveryHint(status, statusReason, latestError string) string {
	blob := strings.ToLower(statusReason + " " + latestError)
	switch {
	case strings.Contains(blob, "maximum context length"), strings.Contains(blob, "context length"):
		return "finalize prompt exceeded the model context window; re-run (chapter_finder tool output is now bounded)"
	case strings.Contains(blob, "connection refused"), strings.Contains(blob, "dial tcp"), strings.Contains(blob, "no route to host"):
		return "a provider endpoint was unreachable; verify Spark endpoints, then re-run"
	case strings.Contains(blob, "no work units"):
		return "resume produced no work; re-run from scratch"
	case strings.Contains(blob, "worker queue full"):
		return "CPU queue backpressure; re-run (overflow now requeues)"
	case status == "processing":
		return "still processing or stalled; check for an active job"
	default:
		return "inspect the error and re-run"
	}
}

func (e *RunSummaryEndpoint) handler(w http.ResponseWriter, r *http.Request) {
	client := svcctx.DefraClientFrom(r.Context())
	if client == nil {
		writeError(w, http.StatusServiceUnavailable, "defra client not initialized")
		return
	}

	resp, err := client.Query(r.Context(), `{
		Book {
			_docID
			title
			status
			status_reason
		}
	}`)
	if err != nil {
		writeError(w, http.StatusInternalServerError, err.Error())
		return
	}
	if msg := resp.Error(); msg != "" {
		writeError(w, http.StatusInternalServerError, msg)
		return
	}

	// Build a bookID -> latest failed error map from process-book job records.
	// Manager.List is NOT ordered and caps at 100 by default, so request a high
	// limit and pick the newest failed record per book explicitly (by
	// CompletedAt, falling back to CreatedAt) rather than trusting result order.
	latestErr := map[string]string{}
	if jm := svcctx.JobManagerFrom(r.Context()); jm != nil {
		if records, lerr := jm.List(r.Context(), jobs.ListFilter{JobType: "process-book", Limit: 10000}); lerr == nil {
			latestAt := map[string]time.Time{}
			for _, rec := range records {
				if rec.Status != jobs.StatusFailed || rec.Error == "" {
					continue
				}
				at := rec.CreatedAt
				if rec.CompletedAt != nil {
					at = *rec.CompletedAt
				}
				if prev, ok := latestAt[rec.BookID]; !ok || at.After(prev) {
					latestAt[rec.BookID] = at
					latestErr[rec.BookID] = rec.Error
				}
			}
		}
	}

	out := RunSummaryResponse{Counts: map[string]int{}}
	if data, ok := resp.Data["Book"].([]any); ok {
		for _, item := range data {
			m, ok := item.(map[string]any)
			if !ok {
				continue
			}
			b := BookSummary{
				ID:           getString(m, "_docID"),
				Title:        getString(m, "title"),
				Status:       getString(m, "status"),
				StatusReason: getString(m, "status_reason"),
			}
			b.LatestError = latestErr[b.ID]
			if b.Status != "complete" {
				b.RecoveryHint = recoveryHint(b.Status, b.StatusReason, b.LatestError)
			}
			out.Counts[b.Status]++
			out.Books = append(out.Books, b)
			out.Total++
		}
	}
	sort.Slice(out.Books, func(i, j int) bool { return out.Books[i].Status > out.Books[j].Status })

	writeJSON(w, http.StatusOK, out)
}

func (e *RunSummaryEndpoint) Command(getServerURL func() string) *cobra.Command {
	return &cobra.Command{
		Use:   "run-summary",
		Short: "Fleet scoreboard: books by status + recovery hints",
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			client := api.NewClient(getServerURL())
			var resp RunSummaryResponse
			if err := client.Get(ctx, "/api/run/summary", &resp); err != nil {
				return err
			}
			return api.Output(resp)
		},
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/server/endpoints/ -run TestRecoveryHint -v`
Expected: PASS.

- [ ] **Step 5: Register the HTTP route**

In `internal/server/endpoints/registry.go`, in `All()`, add near the health endpoints:

```go
		// Run summary (fleet scoreboard)
		&RunSummaryEndpoint{},
```

- [ ] **Step 6: Register the CLI command**

In `cmd/shelf/api.go`, near the other top-level `apiCmd.AddCommand(...)` lines (~line 69), add:

```go
	apiCmd.AddCommand((&endpoints.RunSummaryEndpoint{}).Command(getServerURL))
```

- [ ] **Step 7: Build backend to confirm wiring compiles**

Run: `make build:backend`
Expected: build succeeds.

- [ ] **Step 8: Commit**

```bash
git add internal/server/endpoints/run_summary.go internal/server/endpoints/registry.go cmd/shelf/api.go internal/server/endpoints/run_summary_test.go
git commit -m "feat: add /api/run/summary fleet scoreboard endpoint + CLI"
```

---

# GROUP 3 — chapter_finder token caps

### Task 6: Cap `get_page_ocr` output

**Files:**
- Modify: `internal/agents/chapter_finder/tools/get_page_ocr.go`
- Test: `internal/agents/chapter_finder/tools/get_page_ocr_test.go` (create)

**Interfaces:**
- Consumes: `tools.New(Config{Book, Entry, ExcludedRanges})`; `(*ChapterFinderTools).getPageOcr(ctx, pageNum) (string, error)`.
- Produces: `const maxPageOcrToolTextRunes`; `ocr_text_truncated` bool in the JSON result.

- [ ] **Step 1: Write the failing test**

Create `internal/agents/chapter_finder/tools/get_page_ocr_test.go`:

```go
package tools

import (
	"context"
	"encoding/json"
	"strings"
	"testing"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGetPageOcrTruncatesLongText(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 20
	longText := "CHAPTER FOURTEEN\n" + strings.Repeat("body text ", 4000)
	page := book.GetOrCreatePage(14)
	page.SetOcrMarkdown(longText)

	toolset := New(Config{
		Book:  book,
		Entry: &chapter_finder.EntryToFind{Identifier: "14", ExpectedNearPage: 14},
	})

	got, err := toolset.getPageOcr(context.Background(), 14)
	if err != nil {
		t.Fatalf("getPageOcr error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON: %v\n%s", err, got)
	}
	ocrText, _ := payload["ocr_text"].(string)
	if len([]rune(ocrText)) > maxPageOcrToolTextRunes+50 {
		t.Fatalf("ocr_text not truncated: %d runes", len([]rune(ocrText)))
	}
	if payload["ocr_text_truncated"] != true {
		t.Fatalf("ocr_text_truncated = %#v, want true", payload["ocr_text_truncated"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/agents/chapter_finder/tools/ -run TestGetPageOcrTruncatesLongText -v`
Expected: FAIL — `maxPageOcrToolTextRunes` undefined / text not truncated.

- [ ] **Step 3: Add the cap**

In `internal/agents/chapter_finder/tools/get_page_ocr.go`, add a const near the top (after imports):

```go
// maxPageOcrToolTextRunes bounds the OCR text returned to the agent. A chapter
// heading is at the top of a page, so the lead is sufficient for validation and
// this keeps a single tool result from blowing the model context window.
const maxPageOcrToolTextRunes = 6000
```

Then, in `getPageOcr`, after `text, err := t.getPageOcrMarkdown(ctx, pageNum)` succeeds and before building `result`, truncate:

```go
	truncated := false
	if runes := []rune(text); len(runes) > maxPageOcrToolTextRunes {
		text = string(runes[:maxPageOcrToolTextRunes])
		truncated = true
	}

	result := map[string]any{
		"page_num":           pageNum,
		"ocr_text":           text,
		"char_count":         len(text),
		"ocr_text_truncated": truncated,
		"in_excluded_range":  inExcluded,
	}
```

(Replace the existing `result := map[string]any{...}` literal with the one above; keep the subsequent `if inExcluded { ... }` warning block unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/agents/chapter_finder/tools/ -run TestGetPageOcrTruncatesLongText -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add internal/agents/chapter_finder/tools/get_page_ocr.go internal/agents/chapter_finder/tools/get_page_ocr_test.go
git commit -m "feat: cap chapter_finder get_page_ocr output size"
```

---

### Task 7: Cap `grep_text` match count

**Files:**
- Modify: `internal/agents/chapter_finder/tools/grep_text.go`
- Test: `internal/agents/chapter_finder/tools/grep_text_test.go` (create)

**Interfaces:**
- Consumes: `tools.New(Config{...})`; `(*ChapterFinderTools).grepText(ctx, query) (string, error)`; `t.entry.ExpectedNearPage`.
- Produces: `const maxGrepMatches`; `matches_truncated` bool + `total_match_pages` int in the JSON result.

- [ ] **Step 1: Write the failing test**

Create `internal/agents/chapter_finder/tools/grep_text_test.go`:

```go
package tools

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	chapter_finder "github.com/jackzampolin/shelf/internal/agents/chapter_finder"
	"github.com/jackzampolin/shelf/internal/jobs/common"
)

func TestGrepTextCapsMatchCount(t *testing.T) {
	book := common.NewBookState("book-1")
	book.TotalPages = 400
	// "war" appears on every page -> without a cap this returns 400 match records.
	for p := 1; p <= 400; p++ {
		book.GetOrCreatePage(p).SetOcrMarkdown(fmt.Sprintf("page %d discussing the war effort", p))
	}

	toolset := New(Config{
		Book:  book,
		Entry: &chapter_finder.EntryToFind{Identifier: "14", ExpectedNearPage: 200},
	})

	got, err := toolset.grepText(context.Background(), "war")
	if err != nil {
		t.Fatalf("grepText error: %v", err)
	}

	var payload map[string]any
	if err := json.Unmarshal([]byte(got), &payload); err != nil {
		t.Fatalf("invalid JSON: %v\n%s", err, got)
	}
	matches, _ := payload["matches"].([]any)
	if len(matches) > maxGrepMatches {
		t.Fatalf("returned %d matches, want <= %d", len(matches), maxGrepMatches)
	}
	if payload["matches_truncated"] != true {
		t.Fatalf("matches_truncated = %#v, want true", payload["matches_truncated"])
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/agents/chapter_finder/tools/ -run TestGrepTextCapsMatchCount -v`
Expected: FAIL — `maxGrepMatches` undefined / 400 matches returned.

- [ ] **Step 3: Add the cap**

In `internal/agents/chapter_finder/tools/grep_text.go`, add a const near the `GrepMatch` type:

```go
// maxGrepMatches bounds how many per-page match records are serialized back to
// the agent. Clusters are computed over the full match set first; only the
// output list is capped (nearest to the entry's expected page), so a broad
// query on a long book cannot exceed the model context window.
const maxGrepMatches = 50
```

Then, in `grepText`, after `clusters := identifyClusters(validMatches)` (clusters still computed over the full set) and before building the final `jsonSuccess`, cap the `matches` slice by proximity to the expected page:

```go
	totalMatchPages := len(matches)
	matchesTruncated := false
	if len(matches) > maxGrepMatches {
		matchesTruncated = true
		near := 0
		if t.entry != nil {
			near = t.entry.ExpectedNearPage
		}
		sort.Slice(matches, func(i, j int) bool {
			return absInt(matches[i].ScanPage-near) < absInt(matches[j].ScanPage-near)
		})
		matches = matches[:maxGrepMatches]
		sort.Slice(matches, func(i, j int) bool {
			return matches[i].ScanPage < matches[j].ScanPage
		})
	}

	return jsonSuccess(map[string]any{
		"query":             query,
		"matches":           matches,
		"matches_truncated": matchesTruncated,
		"total_match_pages": totalMatchPages,
		"clusters":          clusters,
		"summary":           summary,
		"message":           fmt.Sprintf("Found matches on %d pages (showing %d)", totalMatchPages, len(matches)),
	}), nil
```

(Replace the existing final `return jsonSuccess(map[string]any{...})` with the block above.)

Add the small helper at the bottom of the file:

```go
func absInt(x int) int {
	if x < 0 {
		return -x
	}
	return x
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/agents/chapter_finder/tools/ -run TestGrepTextCapsMatchCount -v`
Expected: PASS.

- [ ] **Step 5: Run the full tools package to check for regressions**

Run: `go test ./internal/agents/chapter_finder/... -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add internal/agents/chapter_finder/tools/grep_text.go internal/agents/chapter_finder/tools/grep_text_test.go
git commit -m "feat: cap chapter_finder grep_text match count"
```

---

# GROUP 4 — Retryable vs failable classification

### Task 8: Exported `jobs.IsRetriableError` + provider-pool delegation

**Files:**
- Create: `internal/jobs/error_class.go`
- Modify: `internal/jobs/provider_pool.go:487-528` (`isRetriableError`)
- Test: `internal/jobs/error_class_test.go` (create)

**Interfaces:**
- Produces: `jobs.IsRetriableError(err error) bool` (pure, no side effects).
- Consumes (refactor): `(*ProviderWorkerPool).isRetriableError` delegates classification to `IsRetriableError` while keeping its rate-limiter bookkeeping.

- [ ] **Step 1: Write the failing test**

Create `internal/jobs/error_class_test.go`:

```go
package jobs

import (
	"fmt"
	"testing"
)

func TestIsRetriableError(t *testing.T) {
	retriable := []string{
		"request failed: dial tcp 100.86.62.91:8000: connect: connection refused",
		"context deadline exceeded",
		"Client.Timeout exceeded while awaiting headers",
		"connection closed: EOF",
		"OpenRouter error (status 503): overloaded",
		"OpenRouter error (status 429): rate limit",
	}
	for _, s := range retriable {
		if !IsRetriableError(fmt.Errorf("%s", s)) {
			t.Errorf("IsRetriableError(%q) = false, want true", s)
		}
	}

	failable := []string{
		"OpenRouter error (status 400): This model's maximum context length is 65536 tokens",
		"OpenRouter error (status 404): no such model",
		"schema validation failed",
		"",
	}
	for _, s := range failable {
		if IsRetriableError(fmt.Errorf("%s", s)) {
			t.Errorf("IsRetriableError(%q) = true, want false", s)
		}
	}
	if IsRetriableError(nil) {
		t.Error("IsRetriableError(nil) = true, want false")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/ -run TestIsRetriableError -v`
Expected: FAIL — `IsRetriableError undefined`.

- [ ] **Step 3: Create the classifier**

Create `internal/jobs/error_class.go`:

```go
package jobs

import "strings"

// IsRetriableError reports whether err looks like a transient failure worth
// retrying (network blips, timeouts, rate limits, 5xx). Deterministic errors
// (4xx, context-length overflow, schema/parse failures) return false so callers
// can fail fast instead of burning retries. Pure: no side effects.
func IsRetriableError(err error) bool {
	if err == nil {
		return false
	}
	s := strings.ToLower(err.Error())
	switch {
	case strings.Contains(s, "status 500"),
		strings.Contains(s, "status 502"),
		strings.Contains(s, "status 503"),
		strings.Contains(s, "status 504"):
		return true
	case strings.Contains(s, "status 429"), strings.Contains(s, "rate limit"):
		return true
	case strings.Contains(s, "timeout"), strings.Contains(s, "deadline exceeded"):
		return true
	case strings.Contains(s, "connection refused"),
		strings.Contains(s, "connection reset"),
		strings.Contains(s, "eof"):
		return true
	default:
		return false
	}
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/jobs/ -run TestIsRetriableError -v`
Expected: PASS.

- [ ] **Step 5: Delegate `provider_pool.go` classification to `IsRetriableError`**

In `internal/jobs/provider_pool.go`, replace the body of `isRetriableError` (keep the method — the rate-limiter side effects must stay) with:

```go
func (p *ProviderWorkerPool) isRetriableError(err error) bool {
	if err == nil {
		return false
	}

	// Structured rate-limit error carries a precise RetryAfter.
	if rle, ok := providers.IsRateLimitError(err); ok {
		p.rateLimiter.Record429(rle.RetryAfter)
		p.logger.Debug("rate limit hit, backing off", "retry_after", rle.RetryAfter)
		return true
	}

	// Record a coarse 429 backoff before delegating classification.
	errStr := strings.ToLower(err.Error())
	if strings.Contains(errStr, "status 429") || strings.Contains(errStr, "rate limit") {
		p.rateLimiter.Record429(5 * time.Second)
	}

	return IsRetriableError(err)
}
```

- [ ] **Step 6: Verify no regression in the existing classification test**

Run: `go test ./internal/jobs/ -run 'TestIsRetriableError|Retriable' -v`
Expected: PASS (including the existing `isRetriableError` assertions in `jobs_test.go`).

- [ ] **Step 7: Commit**

```bash
git add internal/jobs/error_class.go internal/jobs/provider_pool.go internal/jobs/error_class_test.go
git commit -m "refactor: extract pure jobs.IsRetriableError classifier"
```

---

### Task 9: Fail fast on non-retriable book-op errors in `OnComplete`

**Files:**
- Modify: `internal/jobs/process_book/job/job.go` (metadata / toc_finder / toc_extract failure cases, ~lines 281-310)
- Test: `internal/jobs/process_book/job/book_op_retry_test.go` (add cases)

**Interfaces:**
- Consumes: `jobs.IsRetriableError` (Task 8); existing `createBookOpRetryUnit`, `markBookOpRetryExhausted`.
- Produces: retry gating that requires the error to be retriable (behavior change; no new symbols).

- [ ] **Step 1: Write the failing test**

Add to `internal/jobs/process_book/job/book_op_retry_test.go`:

```go
func TestOnCompleteBookOpFailsFastOnNonRetriableError(t *testing.T) {
	j := newMetadataRetryJob()

	const unitID = "wu-metadata-1"
	j.RegisterWorkUnit(unitID, WorkUnitInfo{
		UnitType:   WorkUnitTypeMetadata,
		RetryCount: 0, // fresh: would normally retry
	})

	_, err := j.OnComplete(context.Background(), jobs.WorkResult{
		WorkUnitID: unitID,
		Success:    false,
		Error:      fmt.Errorf("OpenRouter error (status 400): This model's maximum context length is 65536 tokens"),
	})
	if err == nil {
		t.Fatal("OnComplete error = nil, want fatal error (non-retriable 400 should not retry)")
	}
	if !j.Book.GetMetadataState().IsFailed() {
		t.Fatal("metadata should be marked failed on a non-retriable error")
	}
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/process_book/job/ -run TestOnCompleteBookOpFailsFastOnNonRetriableError -v`
Expected: FAIL — a retry unit is created (err is nil) because the code retries on attempt count regardless of error type.

- [ ] **Step 3: Gate the three book-op retries on `IsRetriableError`**

In `internal/jobs/process_book/job/job.go`, in the `if !result.Success` switch, change the retry condition in the `WorkUnitTypeMetadata`, `WorkUnitTypeTocFinder`, and `WorkUnitTypeTocExtract` cases from:

```go
			if info.RetryCount < MaxBookOpRetries {
```

to:

```go
			if info.RetryCount < MaxBookOpRetries && jobs.IsRetriableError(result.Error) {
```

(All three cases use the identical line; update each. `jobs` is already imported in `job.go`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `go test ./internal/jobs/process_book/job/ -run TestOnCompleteBookOpFailsFastOnNonRetriableError -v`
Expected: PASS.

- [ ] **Step 5: Verify existing retry tests still pass (transient errors still retry)**

Run: `go test ./internal/jobs/process_book/job/ -run 'TestOnCompleteBookOperation' -v`
Expected: PASS — the existing tests use `connection refused` (retriable), so retry behavior is preserved.

- [ ] **Step 6: Commit**

```bash
git add internal/jobs/process_book/job/job.go internal/jobs/process_book/job/book_op_retry_test.go
git commit -m "feat: fail fast on non-retriable book-op errors"
```

---

# GROUP 5 — CPU queue-full backpressure (optional / last)

> This group is lowest priority: with Group 1 in place, a CPU-queue-full failure now cleanly marks the book `failed` and shows on the scoreboard, and re-runs usually succeed. This group upgrades it from "fail + re-run" to "requeue transparently."

### Task 10: Requeue `ErrWorkerQueueFull` with backoff instead of failing

**Files:**
- Modify: `internal/jobs/scheduler.go` (add `requeue` channel + `requeueLoop` + `resubmitWithBackoff` + `emitFailure`; init channel in `NewScheduler`; start loop in `Start`)
- Modify: `internal/jobs/scheduler_routing.go` (requeue on `ErrWorkerQueueFull`; use `emitFailure`)
- Test: `internal/jobs/scheduler_requeue_test.go` (create)

**Interfaces:**
- Consumes: `ErrWorkerQueueFull`, `(*Scheduler).findPool`, `s.results`, `workerResult`, `WorkResult`.
- Produces: `(*Scheduler).emitFailure(unit *WorkUnit, err error)`; `s.requeue chan *WorkUnit`; `const cpuRequeueBackoff`.

- [ ] **Step 1: Write the failing test**

Create `internal/jobs/scheduler_requeue_test.go`:

```go
package jobs

import (
	"errors"
	"log/slog"
	"testing"
)

func TestEnqueueRequeuesOnQueueFull(t *testing.T) {
	s := NewScheduler(SchedulerConfig{Logger: slog.Default()})

	// NewCPUWorkerPool normalizes QueueSize <= 0 to 10000, so use a real capacity
	// of 1 and pre-fill the single slot (no workers started) to force the next
	// Submit to return ErrWorkerQueueFull.
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

	// The unit must be parked on the requeue channel, NOT emitted as a failure.
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
		if wr.Result.Error != nil && errors.Is(wr.Result.Error, ErrWorkerQueueFull) {
			t.Fatal("queue-full should requeue, not emit a failure result")
		}
	default:
		// good: no failure result emitted
	}
}
```

(Reuses `stubFailJob` from `scheduler_failbook_test.go`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `go test ./internal/jobs/ -run TestEnqueueRequeuesOnQueueFull -v`
Expected: FAIL — `s.requeue` undefined (and today the unit is emitted as a failure).

- [ ] **Step 3: Add the requeue channel, loop, and helpers**

In `internal/jobs/scheduler.go`, add a field to the `Scheduler` struct:

```go
	// Requeue buffer for units bounced by a full pool queue (backpressure).
	requeue chan *WorkUnit
```

Add a const near the top of the file:

```go
// cpuRequeueBackoff is the delay between resubmit attempts for a unit bounced
// by a full pool queue.
const cpuRequeueBackoff = 250 * time.Millisecond
```

In `NewScheduler`, initialize the channel alongside the other maps/channels (buffer generously so parking rarely blocks):

```go
	requeue: make(chan *WorkUnit, 100000),
```

(Add this to the `&Scheduler{...}` literal in `NewScheduler`; match the existing field-init style.)

Add the loop and helpers:

```go
// requeueLoop drains the requeue buffer, retrying each parked unit until the
// pool accepts it (or the context is cancelled). Runs in its own goroutine so
// it never blocks the results loop.
func (s *Scheduler) requeueLoop(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case unit := <-s.requeue:
			s.resubmitWithBackoff(ctx, unit)
		}
	}
}

func (s *Scheduler) resubmitWithBackoff(ctx context.Context, unit *WorkUnit) {
	pool := s.findPool(unit)
	if pool == nil {
		s.emitFailure(unit, fmt.Errorf("no pool available for type %s provider %s", unit.Type, unit.Provider))
		return
	}
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		err := pool.Submit(unit)
		if err == nil {
			return
		}
		if !errors.Is(err, ErrWorkerQueueFull) {
			s.emitFailure(unit, err)
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-time.After(cpuRequeueBackoff):
		}
	}
}

// emitFailure sends a failed WorkResult for a unit that could not be routed.
func (s *Scheduler) emitFailure(unit *WorkUnit, err error) {
	s.results <- workerResult{
		JobID: unit.JobID,
		Unit:  unit,
		Result: WorkResult{
			WorkUnitID: unit.ID,
			Success:    false,
			Error:      err,
		},
	}
}
```

Ensure `errors`, `fmt`, and `time` are imported in `scheduler.go` (add any missing).

In `Start`, start the loop next to the reconciler loop (Task 4, Step 5):

```go
	go s.requeueLoop(ctx)
```

- [ ] **Step 4: Requeue on `ErrWorkerQueueFull` in `enqueueUnits`**

In `internal/jobs/scheduler_routing.go`, add `"errors"` to imports, and change the `pool.Submit` error handling from:

```go
		if err := pool.Submit(unit); err != nil {
			s.logger.Warn("failed to submit to pool", "pool", pool.Name(), "error", err)
			// Send failure result
			s.results <- workerResult{
				JobID: jobID,
				Unit:  unit,
				Result: WorkResult{
					WorkUnitID: unit.ID,
					Success:    false,
					Error:      err,
				},
			}
		}
```

to:

```go
		if err := pool.Submit(unit); err != nil {
			if errors.Is(err, ErrWorkerQueueFull) {
				// Backpressure: park for retry instead of failing. The unit stays
				// counted in s.pending, so completion accounting is unchanged.
				select {
				case s.requeue <- unit:
					continue
				default:
					// Requeue buffer itself is full: fall back to a failure result.
				}
			}
			s.logger.Warn("failed to submit to pool", "pool", pool.Name(), "error", err)
			s.emitFailure(unit, err)
		}
```

Also replace the `pool == nil` failure block's inline `s.results <- workerResult{...}` with `s.emitFailure(unit, fmt.Errorf("no pool available for type %s provider %s", unit.Type, unit.Provider))` for consistency (optional but tidy; `unit.JobID` is already set above).

- [ ] **Step 5: Run test to verify it passes**

Run: `go test ./internal/jobs/ -run TestEnqueueRequeuesOnQueueFull -v`
Expected: PASS.

- [ ] **Step 6: Run the full jobs package**

Run: `go test ./internal/jobs/ -v`
Expected: PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add internal/jobs/scheduler.go internal/jobs/scheduler_routing.go internal/jobs/scheduler_requeue_test.go
git commit -m "feat: requeue CPU-queue-full units as backpressure"
```

---

## Final verification

- [ ] **Full build + test**

Run: `make build:backend && make test`
Expected: build succeeds; all tests pass.

- [ ] **Sanity: scoreboard endpoint (cost-safe)**

⚠️ **`shelf serve` is NOT inert.** On startup it calls `scheduler.Resume(ctx)` (`internal/server/server.go`), which re-enqueues any Job records still in `running` — that spawns real OCR/LLM work. Do not start `shelf serve` just to check whether it is safe.

Only run the live smoke test when the operator already knows the DB is wiped / newly initialized / has no `running` Job records. If a server is already running from a known-safe DB, `./build/shelf api jobs list --status running -o json` may be used as an extra check, but it is not a safe precondition for starting the server.

When the DB state is known safe, start the server and hit the endpoint:
```bash
./build/shelf serve                      # terminal 1
./build/shelf api run-summary -o json    # terminal 2
```
Expected: JSON with `total`, `counts` by status, and per-book `recovery_hint` for non-complete books. Stop the server (Ctrl-C).

If you cannot guarantee the DB has no resumable jobs, skip the live test — `make test` above already covers the endpoint logic via `TestRecoveryHint`.

---

## Self-Review notes (traceability to the design)

- **American Caesar (finalize context-400):** Task 1–3 mark the book `failed` when the finalize job dies (was: stuck `processing`). Task 6/7 bound the chapter_finder prompt so a re-run no longer hits the 65536 ceiling. Task 9 ensures a deterministic 400 never wastes retries.
- **China's Good War ("no work units and is not done"):** Task 3's `Resume` wiring marks the book `failed` on the dead-end; Task 4's reconciler is the backstop; the scoreboard's hint says "re-run from scratch".
- **A Bitter Revolution (endpoint down):** Task 3 marks it `failed` instead of stranding; Task 8/9 keep `connection refused` retriable so a brief blip retries, while a sustained outage still terminates cleanly for the daily re-run.
- **CPU-queue-full class:** Task 10 requeues instead of failing; Group 1 is the safety net if the requeue buffer itself overflows.
- **Monitoring:** Task 5 replaces log-parsing with `shelf api run-summary`.

## Review round 1 — findings addressed

- **Full scheduler-path coverage (High):** Task 3 now wires `failBookForJob` into `startJobAsync` (the primary submit path) and all four `Resume` branches; the two factory-failure branches use `failBookByRecord`, which also flips the stale `running` record to `failed` so the reconciler (which correctly skips `running` records) can catch it.
- **Cost-safe verification (High):** the final smoke test now warns that `serve` runs `Resume` and requires operator-known safe DB state (or skips to `go test`).
- **status_reason clearing (Medium):** Task 1 Step 5b clears `status_reason` on `processing`/`complete` writes so a stale reason never sticks to a book that later succeeds.
- **Requeue test triggers queue-full (Medium):** Task 10's test uses `QueueSize: 1` pre-filled (not `0`, which normalizes to 10000).
- **Deterministic latest error (Medium):** Task 5 requests a high limit and picks the newest failed record per book by `CompletedAt`/`CreatedAt` rather than trusting list order.

## Review round 2 — findings addressed

- **No unsafe live pre-check:** the final smoke test no longer suggests using `shelf api jobs list` before starting any server; it requires operator-known safe DB state or skips the live test.
- **All status writers clear stale reasons:** Task 1 now includes `internal/jobs/common/persist.go` and tests the deprecated package-level `common.PersistBookStatus` helper.
- **Scheduler branch tests:** Task 3 now includes focused tests for `startJobAsync` start-error/no-work failures and the record-based fallback.
- **No `svcctx` import cycle in package `jobs`:** `failBookByRecord` and the reconciler use `s.manager.defra` instead of `svcctx.DefraClientFrom`.
