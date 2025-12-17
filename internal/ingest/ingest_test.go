package ingest

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

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

func TestExtractImages(t *testing.T) {
	// Use the test fixture
	testPDF := filepath.Join("..", "..", "testdata", "test-book.pdf")
	if _, err := os.Stat(testPDF); os.IsNotExist(err) {
		t.Skip("test fixture not found")
	}

	// Create temp output directory
	outDir, err := os.MkdirTemp("", "ingest-test-*")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(outDir)

	// Extract images
	count, err := extractImages(testPDF, outDir, 0)
	if err != nil {
		t.Fatalf("extractImages failed: %v", err)
	}

	if count != 615 {
		t.Errorf("expected 615 pages, got %d", count)
	}

	// Verify files exist with correct naming
	for i := 1; i <= count; i++ {
		path := filepath.Join(outDir, fmt.Sprintf("page_%04d.png", i))
		if _, err := os.Stat(path); os.IsNotExist(err) {
			t.Errorf("expected file %s to exist", path)
		}
	}
}
