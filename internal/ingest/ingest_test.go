package ingest

import (
	"context"
	"testing"

	"github.com/jackzampolin/shelf/internal/jobs"
)

func TestNewJob(t *testing.T) {
	t.Run("creates job with provided title", func(t *testing.T) {
		job := NewJob(JobConfig{
			PDFPaths: []string{"book-1.pdf", "book-2.pdf"},
			Title:    "My Book",
			Author:   "Test Author",
		})

		if job.Type() != JobType {
			t.Errorf("Type() = %q, want %q", job.Type(), JobType)
		}
		if job.title != "My Book" {
			t.Errorf("title = %q, want %q", job.title, "My Book")
		}
		if job.author != "Test Author" {
			t.Errorf("author = %q, want %q", job.author, "Test Author")
		}
	})

	t.Run("derives title from first PDF", func(t *testing.T) {
		job := NewJob(JobConfig{
			PDFPaths: []string{"crusade-europe-1.pdf"},
		})

		if job.title != "crusade-europe" {
			t.Errorf("title = %q, want %q", job.title, "crusade-europe")
		}
	})

	t.Run("sorts PDFs by number", func(t *testing.T) {
		job := NewJob(JobConfig{
			PDFPaths: []string{"book-3.pdf", "book-1.pdf", "book-2.pdf"},
		})

		expected := []string{"book-1.pdf", "book-2.pdf", "book-3.pdf"}
		for i, p := range job.pdfPaths {
			if p != expected[i] {
				t.Errorf("pdfPaths[%d] = %q, want %q", i, p, expected[i])
			}
		}
	})

	t.Run("generates unique book ID", func(t *testing.T) {
		job1 := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})
		job2 := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})

		if job1.bookID == job2.bookID {
			t.Error("expected unique book IDs")
		}
	})
}

func TestJob_RecordID(t *testing.T) {
	job := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})

	// Initially empty
	if job.ID() != "" {
		t.Errorf("ID() = %q, want empty", job.ID())
	}

	// Set and get
	job.SetRecordID("test-record-id")
	if job.ID() != "test-record-id" {
		t.Errorf("ID() = %q, want %q", job.ID(), "test-record-id")
	}
}

func TestJob_Done(t *testing.T) {
	job := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})

	if job.Done() {
		t.Error("new job should not be done")
	}
}

func TestJob_Status(t *testing.T) {
	job := NewJob(JobConfig{
		PDFPaths: []string{"book.pdf"},
		Title:    "Test Book",
		Author:   "Test Author",
	})

	ctx := context.Background()
	status, err := job.Status(ctx)
	if err != nil {
		t.Fatalf("Status() error = %v", err)
	}

	if status["title"] != "Test Book" {
		t.Errorf("status[title] = %q, want %q", status["title"], "Test Book")
	}
	if status["author"] != "Test Author" {
		t.Errorf("status[author] = %q, want %q", status["author"], "Test Author")
	}
	if status["total_pages"] != "0" {
		t.Errorf("status[total_pages] = %q, want %q", status["total_pages"], "0")
	}
}

func TestJob_Progress(t *testing.T) {
	job := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})

	progress := job.Progress()

	copy, ok := progress["copy"]
	if !ok {
		t.Fatal("expected 'copy' in progress")
	}
	if copy.TotalExpected != 1 {
		t.Errorf("copy.TotalExpected = %d, want 1", copy.TotalExpected)
	}
}

func TestJob_MetricsFor(t *testing.T) {
	job := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})

	if job.MetricsFor() != nil {
		t.Error("MetricsFor() should return nil for ingest jobs")
	}
}

func TestJob_BookID(t *testing.T) {
	job := NewJob(JobConfig{PDFPaths: []string{"book.pdf"}})

	if job.BookID() != "" {
		t.Errorf("BookID() = %q, want empty before completion", job.BookID())
	}
}

func TestSortPDFsByNumber(t *testing.T) {
	tests := []struct {
		name     string
		input    []string
		expected []string
	}{
		{
			name:     "already sorted",
			input:    []string{"book-1.pdf", "book-2.pdf", "book-3.pdf"},
			expected: []string{"book-1.pdf", "book-2.pdf", "book-3.pdf"},
		},
		{
			name:     "reverse order",
			input:    []string{"book-3.pdf", "book-2.pdf", "book-1.pdf"},
			expected: []string{"book-1.pdf", "book-2.pdf", "book-3.pdf"},
		},
		{
			name:     "mixed with double digits",
			input:    []string{"book-10.pdf", "book-2.pdf", "book-1.pdf"},
			expected: []string{"book-1.pdf", "book-2.pdf", "book-10.pdf"},
		},
		{
			name:     "single file without number",
			input:    []string{"book.pdf"},
			expected: []string{"book.pdf"},
		},
		{
			name:     "numbered and unnumbered",
			input:    []string{"book-2.pdf", "book.pdf", "book-1.pdf"},
			expected: []string{"book.pdf", "book-1.pdf", "book-2.pdf"},
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := sortPDFsByNumber(tt.input)
			if len(result) != len(tt.expected) {
				t.Fatalf("length mismatch: got %d, want %d", len(result), len(tt.expected))
			}
			for i := range result {
				if result[i] != tt.expected[i] {
					t.Errorf("index %d: got %q, want %q", i, result[i], tt.expected[i])
				}
			}
		})
	}
}

func TestDeriveTitle(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{"/path/to/crusade-europe.pdf", "crusade-europe"},
		{"/path/to/my-book-1.pdf", "my-book"},
		{"/path/to/my-book-10.pdf", "my-book"},
		{"simple.pdf", "simple"},
	}

	for _, tt := range tests {
		t.Run(tt.input, func(t *testing.T) {
			result := deriveTitle(tt.input)
			if result != tt.expected {
				t.Errorf("got %q, want %q", result, tt.expected)
			}
		})
	}
}

func TestExtractPageHandler_InvalidDataType(t *testing.T) {
	handler := ExtractPageHandler()

	// Test with invalid data type
	ctx := context.Background()
	req := &jobs.CPUWorkRequest{
		Task: TaskExtractPage,
		Data: "invalid string data",
	}

	_, err := handler(ctx, req)
	if err == nil {
		t.Error("expected error for invalid data type")
	}
}

func TestExtractPageHandler_MapConversion(t *testing.T) {
	handler := ExtractPageHandler()

	// Test with map data (as would come from JSON deserialization)
	ctx := context.Background()
	req := &jobs.CPUWorkRequest{
		Task: TaskExtractPage,
		Data: map[string]any{
			"PDFPath":   "/nonexistent/test.pdf",
			"PageNum":   float64(1), // JSON numbers are float64
			"OutputNum": float64(1),
			"OutputDir": "/tmp/test-output",
		},
	}

	// This will fail because the PDF doesn't exist, but we're testing
	// that the map conversion works
	_, err := handler(ctx, req)
	if err == nil {
		t.Error("expected error for nonexistent PDF")
	}
	// Verify it's not a type assertion error
	if err.Error() == "invalid data type for extract-page task: map[string]interface {}" {
		t.Error("map conversion should have worked")
	}
}

func TestPageExtractRequest_Fields(t *testing.T) {
	req := PageExtractRequest{
		PDFPath:   "/path/to/test.pdf",
		PageNum:   5,
		OutputNum: 10,
		OutputDir: "/output/dir",
	}

	if req.PDFPath != "/path/to/test.pdf" {
		t.Errorf("PDFPath = %q, want %q", req.PDFPath, "/path/to/test.pdf")
	}
	if req.PageNum != 5 {
		t.Errorf("PageNum = %d, want 5", req.PageNum)
	}
	if req.OutputNum != 10 {
		t.Errorf("OutputNum = %d, want 10", req.OutputNum)
	}
	if req.OutputDir != "/output/dir" {
		t.Errorf("OutputDir = %q, want %q", req.OutputDir, "/output/dir")
	}
}

func TestPageExtractResult_Fields(t *testing.T) {
	result := PageExtractResult{
		OutputPath: "/output/page_0001.png",
		PageNum:    1,
	}

	if result.OutputPath != "/output/page_0001.png" {
		t.Errorf("OutputPath = %q, want %q", result.OutputPath, "/output/page_0001.png")
	}
	if result.PageNum != 1 {
		t.Errorf("PageNum = %d, want 1", result.PageNum)
	}
}

