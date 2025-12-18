package ingest

import (
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

