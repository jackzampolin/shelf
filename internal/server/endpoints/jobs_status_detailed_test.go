package endpoints

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/svcctx"
)

// fakeDetailedStatusDefra answers every GraphQL query getDetailedStatus issues
// (Book, Page, Metric, Book->toc, Chapter, AgentRun) from a single httptest
// server, routing by request body. The canned data exercises every builder
// path: a book with complete metadata, OCR partially complete (7/10 pages),
// per-provider OCR metrics, pattern analysis with finalize progress, a linked
// and an unlinked ToC entry, chapters, stage costs, and one agent run.
// Cost values are binary-exact floats so sums are stable in the golden file.
func fakeDetailedStatusDefra(t *testing.T) *httptest.Server {
	t.Helper()

	// Book query: metadata + structure + finalize progress. The
	// pattern_analysis_json string carries one pattern, one excluded range,
	// and two entries_to_find; finalize counters mark discover and validate
	// phases complete.
	const bookData = `{"data":{"Book":[{
		"page_count": 10,
		"title": "The Test Book",
		"subtitle": "A Golden Fixture",
		"author": "Jane Author",
		"isbn": "978-0-00-000000-0",
		"lccn": "12345678",
		"publisher": "Test Press",
		"publication_year": 1999,
		"language": "en",
		"description": "A book used to pin the detailed status response shape.",
		"cover_page": 1,
		"metadata_started": true,
		"metadata_complete": true,
		"metadata_failed": false,
		"structure_started": true,
		"structure_complete": true,
		"structure_failed": false,
		"pattern_analysis_json": "{\"reasoning\":\"Chapters follow CHAPTER N headings\",\"patterns\":[{\"pattern_type\":\"chapter_heading\",\"level_name\":\"chapter\",\"heading_format\":\"CHAPTER %d\",\"range_start\":\"1\",\"range_end\":\"10\",\"level\":1,\"reasoning\":\"consistent headings\"}],\"excluded_ranges\":[{\"start_page\":1,\"end_page\":2,\"reason\":\"front matter\"}],\"entries_to_find\":[{},{}]}",
		"structure_retries": 1,
		"structure_phase": "finalize",
		"structure_chapters_total": 3,
		"structure_chapters_extracted": 3,
		"structure_chapters_polished": 2,
		"structure_polish_failed": 1,
		"finalize_entries_total": 2,
		"finalize_entries_complete": 2,
		"finalize_entries_found": 1,
		"finalize_gaps_total": 1,
		"finalize_gaps_complete": 1,
		"finalize_gaps_fixes": 1
	}]}}`

	// Page query: 7 of 10 pages OCR-complete (partial OCR).
	const pageData = `{"data":{"Page":[
		{"ocr_complete":true},{"ocr_complete":true},{"ocr_complete":true},
		{"ocr_complete":true},{"ocr_complete":true},{"ocr_complete":true},
		{"ocr_complete":true},{"ocr_complete":false},{"ocr_complete":false},
		{"ocr_complete":false}
	]}}`

	// OCR-stage metrics: two providers so per-provider progress and cost
	// breakdown both have multiple entries.
	const ocrMetricData = `{"data":{"Metric":[
		{"provider":"mistral","stage":"ocr","cost_usd":0.25,"success":true},
		{"provider":"mistral","stage":"ocr","cost_usd":0.125,"success":true},
		{"provider":"deepinfra","stage":"ocr","cost_usd":0.5,"success":true}
	]}}`

	// All-metrics list (BookStageBreakdown): one row per cost-bearing stage.
	const allMetricData = `{"data":{"Metric":[
		{"provider":"mistral","stage":"ocr","cost_usd":0.875,"success":true},
		{"provider":"openrouter","stage":"toc-pattern","cost_usd":0.0625,"success":true},
		{"provider":"openrouter","stage":"metadata","cost_usd":0.125,"success":true},
		{"provider":"openrouter","stage":"toc","cost_usd":0.25,"success":true},
		{"provider":"openrouter","stage":"toc-link","cost_usd":0.125,"success":true},
		{"provider":"openrouter","stage":"toc-discover","cost_usd":0.0625,"success":true},
		{"provider":"openrouter","stage":"toc-validate","cost_usd":0.0625,"success":true},
		{"provider":"openrouter","stage":"structure-classify","cost_usd":0.25,"success":true},
		{"provider":"openrouter","stage":"structure-polish","cost_usd":0.125,"success":true}
	]}}`

	// Book->toc relationship: all stages complete; entries deliberately out
	// of sort order to exercise the sort; one linked extracted entry and one
	// unlinked discovered entry.
	const tocData = `{"data":{"Book":[{"toc":{
		"finder_started":true,"finder_complete":true,"finder_failed":false,
		"toc_found":true,"start_page":3,"end_page":4,
		"extract_started":true,"extract_complete":true,"extract_failed":false,
		"link_started":true,"link_complete":true,"link_failed":false,"link_retries":1,
		"finalize_started":true,"finalize_complete":true,"finalize_failed":false,"finalize_retries":0,
		"entries":[
			{"entry_number":"2","title":"Second Chapter","level":1,"level_name":"chapter","printed_page_number":"15","sort_order":2,"source":"discovered","actual_page":null},
			{"entry_number":"1","title":"First Chapter","level":1,"level_name":"chapter","printed_page_number":"1","sort_order":1,"source":"extracted","actual_page":{"page_num":5}}
		]
	}}]}}`

	const chapterData = `{"data":{"Chapter":[{"_docID":"ch-1"},{"_docID":"ch-2"},{"_docID":"ch-3"}]}}`

	const agentRunData = `{"data":{"AgentRun":[
		{"_docID":"run-1","agent_type":"toc_finder","started_at":"2026-07-01T10:00:00Z","completed_at":"2026-07-01T10:02:00Z","iterations":4,"success":true,"error":""}
	]}}`

	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		raw, _ := io.ReadAll(r.Body)
		body := string(raw)
		w.Header().Set("Content-Type", "application/json")
		switch {
		case strings.Contains(body, "AgentRun("):
			_, _ = io.WriteString(w, agentRunData)
		case strings.Contains(body, "Chapter("):
			_, _ = io.WriteString(w, chapterData)
		case strings.Contains(body, "Page("):
			_, _ = io.WriteString(w, pageData)
		case strings.Contains(body, "Metric(") && strings.Contains(body, "stage:"):
			_, _ = io.WriteString(w, ocrMetricData)
		case strings.Contains(body, "Metric("):
			_, _ = io.WriteString(w, allMetricData)
		case strings.Contains(body, "toc {"):
			_, _ = io.WriteString(w, tocData)
		default:
			_, _ = io.WriteString(w, bookData)
		}
	}))
}

// TestGetDetailedStatus_ResponseShape pins the JSON shape of the detailed job
// status response against a golden file. It gates the extraction of
// getDetailedStatus into per-stage builders: the golden file must not change
// across that refactor. Regenerate with UPDATE_GOLDEN=1.
func TestGetDetailedStatus_ResponseShape(t *testing.T) {
	server := fakeDetailedStatusDefra(t)
	defer server.Close()

	client := defra.NewClient(server.URL)
	// MetricsQuery in the services context routes the cost/progress metric
	// queries through the same fake server so the metrics paths are exercised.
	ctx := svcctx.WithServices(context.Background(), &svcctx.Services{
		DefraClient:  client,
		MetricsQuery: metrics.NewQuery(client),
	})
	resp, err := getDetailedStatus(ctx, client, "book-A", 5)
	if err != nil {
		t.Fatalf("getDetailedStatus: %v", err)
	}
	got, err := json.MarshalIndent(resp, "", "  ")
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	golden := filepath.Join("testdata", "detailed_status_book_a.json")
	if os.Getenv("UPDATE_GOLDEN") == "1" {
		if err := os.MkdirAll(filepath.Dir(golden), 0o755); err != nil { // testdata/ does not exist yet
			t.Fatal(err)
		}
		if err := os.WriteFile(golden, got, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	want, err := os.ReadFile(golden)
	if err != nil {
		t.Fatalf("read golden (run with UPDATE_GOLDEN=1 first): %v", err)
	}
	if !bytes.Equal(bytes.TrimSpace(got), bytes.TrimSpace(want)) {
		t.Errorf("response shape changed:\n--- want\n%s\n--- got\n%s", want, got)
	}
}
