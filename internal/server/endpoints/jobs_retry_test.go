package endpoints

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/jobs/process_book"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

func TestInferResetFromJobError(t *testing.T) {
	tests := []struct {
		name string
		err  string
		want string
	}{
		{
			name: "toc finder work unit",
			err:  `work unit failed (toc_finder): max retries exceeded: connection refused`,
			want: "toc_finder",
		},
		{
			name: "metadata",
			err:  `work unit failed (metadata): request failed`,
			want: "metadata",
		},
		{
			name: "toc link",
			err:  `work unit failed (link_toc): agent failed`,
			want: "toc_link",
		},
		{
			name: "extract work unit",
			err:  `work unit failed (extract): worker queue full: cpu`,
			want: "ocr",
		},
		{
			name: "page extraction",
			err:  `failed to extract page 17: worker queue full: cpu`,
			want: "ocr",
		},
		{
			name: "toc extraction",
			err:  `toc extraction failed: model unavailable`,
			want: "toc_extract",
		},
		{
			name: "toc finalize",
			err:  `finalize toc failed: no usable links`,
			want: "toc_finalize",
		},
		{
			name: "structure",
			err:  `structure build failed: response parse error`,
			want: "structure",
		},
		{
			name: "structure missing linked toc dependency",
			err:  `structure failed to build chapter skeleton: no linked ToC entries found`,
			want: "toc_extract",
		},
		{
			name: "unknown",
			err:  `job failed`,
			want: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := inferResetFromJobError(tt.err); got != tt.want {
				t.Fatalf("inferResetFromJobError() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestJobRecordBookID(t *testing.T) {
	tests := []struct {
		name   string
		record *jobs.Record
		want   string
	}{
		{
			name: "direct book id wins",
			record: &jobs.Record{
				BookID:   "book-direct",
				Metadata: map[string]any{"book_id": "book-meta"},
			},
			want: "book-direct",
		},
		{
			name: "metadata fallback",
			record: &jobs.Record{
				Metadata: map[string]any{"book_id": "book-meta"},
			},
			want: "book-meta",
		},
		{
			name:   "nil record",
			record: nil,
			want:   "",
		},
		{
			name: "missing book id",
			record: &jobs.Record{
				Metadata: map[string]any{"other": "value"},
			},
			want: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := jobRecordBookID(tt.record); got != tt.want {
				t.Fatalf("jobRecordBookID() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestRetryJobEndpointValidation(t *testing.T) {
	records := map[string]*jobs.Record{
		"job-running": {
			ID:      "job-running",
			JobType: process_book.JobType,
			BookID:  "book-1",
			Status:  jobs.StatusRunning,
		},
		"job-wrong-type": {
			ID:      "job-wrong-type",
			JobType: "tts-generate",
			BookID:  "book-1",
			Status:  jobs.StatusFailed,
			Error:   "work unit failed (metadata): request failed",
		},
		"job-missing-book": {
			ID:      "job-missing-book",
			JobType: process_book.JobType,
			Status:  jobs.StatusFailed,
			Error:   "work unit failed (metadata): request failed",
		},
		"job-unknown-stage": {
			ID:      "job-unknown-stage",
			JobType: process_book.JobType,
			BookID:  "book-1",
			Status:  jobs.StatusFailed,
			Error:   "resumed job produced no work units and is not done",
		},
		"job-extract": {
			ID:      "job-extract",
			JobType: process_book.JobType,
			BookID:  "book-1",
			Status:  jobs.StatusFailed,
			Error:   "work unit failed (extract): worker queue full: cpu",
		},
		"job-resume-load": {
			ID:      "job-resume-load",
			JobType: process_book.JobType,
			BookID:  "book-1",
			Status:  jobs.StatusFailed,
			Error:   "resume failed to recreate job: failed to load book: failed to load page states: context deadline exceeded",
		},
	}
	ctx, cleanup := retryEndpointTestContext(t, records)
	defer cleanup()

	tests := []struct {
		name       string
		jobID      string
		body       string
		wantStatus int
		wantBody   string
	}{
		{
			name:       "not found",
			jobID:      "job-missing",
			wantStatus: http.StatusNotFound,
			wantBody:   "job not found",
		},
		{
			name:       "rejects non failed job",
			jobID:      "job-running",
			wantStatus: http.StatusConflict,
			wantBody:   "only failed jobs can be retried",
		},
		{
			name:       "rejects unsupported job type",
			jobID:      "job-wrong-type",
			wantStatus: http.StatusBadRequest,
			wantBody:   "tts-generate",
		},
		{
			name:       "rejects failed job without book id",
			jobID:      "job-missing-book",
			wantStatus: http.StatusBadRequest,
			wantBody:   "failed job record has no book_id",
		},
		{
			name:       "requires reset_from for ambiguous failure",
			jobID:      "job-unknown-stage",
			wantStatus: http.StatusBadRequest,
			wantBody:   "reset_from is required",
		},
		{
			name:       "rejects invalid explicit reset",
			jobID:      "job-extract",
			body:       `{"reset_from":"not-a-stage"}`,
			wantStatus: http.StatusBadRequest,
			wantBody:   "invalid reset_from",
		},
		{
			name:       "inferred reset reaches start path",
			jobID:      "job-extract",
			wantStatus: http.StatusServiceUnavailable,
			wantBody:   "scheduler not initialized",
		},
		{
			name:       "explicit reset reaches start path",
			jobID:      "job-unknown-stage",
			body:       `{"reset_from":"metadata"}`,
			wantStatus: http.StatusServiceUnavailable,
			wantBody:   "scheduler not initialized",
		},
		{
			name:       "resume loader failure retries without destructive reset",
			jobID:      "job-resume-load",
			wantStatus: http.StatusServiceUnavailable,
			wantBody:   "scheduler not initialized",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodPost, "/api/jobs/retry/"+tt.jobID, strings.NewReader(tt.body))
			req.SetPathValue("id", tt.jobID)
			req = req.WithContext(ctx)
			w := httptest.NewRecorder()

			(&RetryJobEndpoint{}).handler(w, req)

			if w.Code != tt.wantStatus {
				t.Fatalf("status = %d, want %d; body=%s", w.Code, tt.wantStatus, w.Body.String())
			}
			if !strings.Contains(w.Body.String(), tt.wantBody) {
				t.Fatalf("body %q missing %q", w.Body.String(), tt.wantBody)
			}
		})
	}
}

func retryEndpointTestContext(t *testing.T, records map[string]*jobs.Record) (context.Context, func()) {
	t.Helper()

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/api/v0/graphql" {
			http.NotFound(w, r)
			return
		}

		var gqlReq defra.GQLRequest
		if err := json.NewDecoder(r.Body).Decode(&gqlReq); err != nil {
			t.Errorf("failed to decode graphql request: %v", err)
			w.WriteHeader(http.StatusBadRequest)
			return
		}

		for id, record := range records {
			if !strings.Contains(gqlReq.Query, fmt.Sprintf("Job(docID: %q)", id)) {
				continue
			}
			if err := json.NewEncoder(w).Encode(map[string]any{
				"data": map[string]any{
					"Job": []any{jobRecordGraphQL(record)},
				},
			}); err != nil {
				t.Errorf("failed to encode graphql response: %v", err)
			}
			return
		}

		if err := json.NewEncoder(w).Encode(map[string]any{
			"data": map[string]any{
				"Job": []any{},
			},
		}); err != nil {
			t.Errorf("failed to encode empty graphql response: %v", err)
		}
	}))

	manager := jobs.NewManager(defra.NewClient(server.URL), nil)
	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		JobManager: manager,
	})

	return ctx, server.Close
}

func jobRecordGraphQL(record *jobs.Record) map[string]any {
	createdAt := record.CreatedAt
	if createdAt.IsZero() {
		createdAt = time.Now().UTC()
	}

	metadata := ""
	if len(record.Metadata) > 0 {
		if data, err := json.Marshal(record.Metadata); err == nil {
			metadata = string(data)
		}
	}

	return map[string]any{
		"_docID":       record.ID,
		"job_type":     record.JobType,
		"book_id":      record.BookID,
		"status":       string(record.Status),
		"created_at":   createdAt.Format(time.RFC3339Nano),
		"started_at":   "",
		"completed_at": "",
		"error":        record.Error,
		"metadata":     metadata,
	}
}
