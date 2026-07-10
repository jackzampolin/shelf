package endpoints

import (
	"fmt"
	"net/http"
	"regexp"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/spf13/cobra"

	"github.com/jackzampolin/shelf/internal/api"
	"github.com/jackzampolin/shelf/internal/jobs"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// RunSummaryResponse is the fleet scoreboard: counts by bucket + per-book detail.
type RunSummaryResponse struct {
	Total  int            `json:"total"`
	Counts map[string]int `json:"counts"`
	Books  []BookSummary  `json:"books"`
}

// BookSummary is one book's terminal/processing state and recovery hint.
type BookSummary struct {
	ID              string     `json:"id"`
	Title           string     `json:"title"`
	Status          string     `json:"status"`
	StatusReason    string     `json:"status_reason,omitempty"`
	LatestJobID     string     `json:"latest_job_id,omitempty"`
	JobStatus       string     `json:"job_status,omitempty"`
	HeartbeatAt     *time.Time `json:"heartbeat_at,omitempty"`
	LastProgressAt  *time.Time `json:"last_progress_at,omitempty"`
	LatestError     string     `json:"latest_error,omitempty"`
	RecoveryHint    string     `json:"recovery_hint,omitempty"`
	RecoveryCommand string     `json:"recovery_command,omitempty"`
}

var failedPagePattern = regexp.MustCompile(`(?:page=|page\s+)(\d+)`)

func failedPage(errorText string) (int, bool) {
	match := failedPagePattern.FindStringSubmatch(strings.ToLower(errorText))
	if len(match) != 2 {
		return 0, false
	}
	page, err := strconv.Atoi(match[1])
	return page, err == nil && page > 0
}

// RunSummaryEndpoint handles GET /api/run/summary.
type RunSummaryEndpoint struct{}

func (e *RunSummaryEndpoint) Route() (string, string, http.HandlerFunc) {
	return "GET", "/api/run/summary", e.handler
}

func (e *RunSummaryEndpoint) RequiresInit() bool { return true }

// recoveryHint maps an observed failure signature to the concrete next action.
func recoveryHint(status, statusReason, latestError string) string {
	// A book that is still (or again) processing has no current error; check this
	// before the error blob so a re-running book does not show a stale failure hint.
	if status == "processing" {
		return "still processing or stalled; check for an active job"
	}
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

	latestRecords := map[string]*jobs.Record{}
	if jm := svcctx.JobManagerFrom(r.Context()); jm != nil {
		records, lerr := jm.List(r.Context(), jobs.ListFilter{JobType: "process-book", Limit: 10000})
		if lerr == nil {
			latestAt := map[string]time.Time{}
			for _, rec := range records {
				if rec == nil || rec.BookID == "" {
					continue
				}
				at := rec.CreatedAt
				if rec.CompletedAt != nil {
					at = *rec.CompletedAt
				}
				if prev, ok := latestAt[rec.BookID]; !ok || at.After(prev) {
					latestAt[rec.BookID] = at
					latestRecords[rec.BookID] = rec
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
			book := BookSummary{
				ID:           getString(m, "_docID"),
				Title:        getString(m, "title"),
				Status:       getString(m, "status"),
				StatusReason: getString(m, "status_reason"),
			}
			latest := latestRecords[book.ID]
			if latest != nil {
				book.LatestJobID = latest.ID
				book.JobStatus = string(latest.Status)
				book.HeartbeatAt = latest.HeartbeatAt
				book.LastProgressAt = latest.LastProgressAt
			}
			// Only attach a prior failed-job error to books that are terminally
			// failed; a processing/complete book's stale error would mislead.
			if book.Status == "failed" && latest != nil && latest.Status == jobs.StatusFailed {
				book.LatestError = latest.Error
			}
			if book.Status != "complete" {
				if latest != nil && latest.Status == jobs.StatusWaitingProvider {
					book.RecoveryHint = "provider unavailable; Shelf is waiting and will replay automatically when health recovers"
				} else {
					book.RecoveryHint = recoveryHint(book.Status, book.StatusReason, book.LatestError)
				}
				failureText := book.StatusReason + " " + book.LatestError
				if page, ok := failedPage(failureText); ok {
					book.RecoveryHint = fmt.Sprintf("page %d failed and remains incomplete; run the targeted OCR repair", page)
					book.RecoveryCommand = fmt.Sprintf("shelf api books repair-ocr %s --pages %d --force", book.ID, page)
				} else if latest != nil && latest.Status == jobs.StatusFailed {
					book.RecoveryCommand = fmt.Sprintf("shelf api jobs retry %s", latest.ID)
				}
			}
			out.Counts[book.Status]++
			out.Books = append(out.Books, book)
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
