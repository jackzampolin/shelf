package endpoints

import (
	"context"
	"encoding/json"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
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
		// A book re-running after a prior failure (processing now, stale failed
		// error attached) must show the processing hint, not the old failure hint.
		{"reprocessing with stale error", "processing", "", "OpenRouter error (status 400): maximum context length", "active job"},
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

// fakeDefra answers the two GraphQL queries the handler issues (Book list and
// Job list) from a single httptest server, routing by request body.
func fakeDefra(t *testing.T) *httptest.Server {
	t.Helper()
	const books = `{"data":{"Book":[
		{"_docID":"book-A","title":"Alpha","status":"failed","status_reason":null},
		{"_docID":"book-B","title":"Bravo","status":"processing","status_reason":null},
		{"_docID":"book-C","title":"Charlie","status":"complete","status_reason":null}
	]}}`
	// Newest failed record listed FIRST to prove selection is by time, not order.
	const jobsData = `{"data":{"Job":[
		{"_docID":"j2","job_type":"process-book","book_id":"book-A","status":"failed","error":"maximum context length exceeded","created_at":"2026-07-01T10:00:00Z","completed_at":"2026-07-01T10:05:00Z"},
		{"_docID":"j1","job_type":"process-book","book_id":"book-A","status":"failed","error":"old transient error","created_at":"2026-06-30T10:00:00Z","completed_at":"2026-06-30T10:05:00Z"}
	]}}`
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(string(body), "Job(") {
			_, _ = io.WriteString(w, jobsData)
			return
		}
		_, _ = io.WriteString(w, books)
	}))
}

func TestRunSummaryHandler(t *testing.T) {
	server := fakeDefra(t)
	defer server.Close()

	client := defra.NewClient(server.URL)
	mgr := jobs.NewManager(client, slog.Default())
	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient: client,
		JobManager:  mgr,
	})

	e := &RunSummaryEndpoint{}
	req := httptest.NewRequest("GET", "/api/run/summary", nil).WithContext(ctx)
	w := httptest.NewRecorder()
	e.handler(w, req)

	if w.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200; body=%s", w.Code, w.Body.String())
	}

	var resp RunSummaryResponse
	if err := json.NewDecoder(w.Body).Decode(&resp); err != nil {
		t.Fatalf("decode: %v", err)
	}

	if resp.Total != 3 {
		t.Fatalf("total = %d, want 3", resp.Total)
	}
	if resp.Counts["failed"] != 1 || resp.Counts["processing"] != 1 || resp.Counts["complete"] != 1 {
		t.Fatalf("counts = %#v, want 1 each of failed/processing/complete", resp.Counts)
	}

	byID := map[string]BookSummary{}
	for _, b := range resp.Books {
		byID[b.ID] = b
	}

	a := byID["book-A"]
	if !strings.Contains(a.LatestError, "maximum context length") {
		t.Fatalf("book-A latest_error = %q, want the NEWEST failed record's error", a.LatestError)
	}
	if !strings.Contains(strings.ToLower(a.RecoveryHint), "context") {
		t.Fatalf("book-A recovery_hint = %q, want a context-length hint", a.RecoveryHint)
	}

	b := byID["book-B"]
	if b.LatestError != "" {
		t.Fatalf("book-B (processing) latest_error = %q, want empty (not terminal)", b.LatestError)
	}
	if !strings.Contains(strings.ToLower(b.RecoveryHint), "active job") {
		t.Fatalf("book-B recovery_hint = %q, want processing hint", b.RecoveryHint)
	}

	c := byID["book-C"]
	if c.RecoveryHint != "" {
		t.Fatalf("book-C (complete) recovery_hint = %q, want empty", c.RecoveryHint)
	}
}

func TestRunSummaryHandlerNilClient(t *testing.T) {
	e := &RunSummaryEndpoint{}
	req := httptest.NewRequest("GET", "/api/run/summary", nil) // no services in context
	w := httptest.NewRecorder()
	e.handler(w, req)
	if w.Code != http.StatusServiceUnavailable {
		t.Fatalf("status = %d, want 503 when defra client missing", w.Code)
	}
}
