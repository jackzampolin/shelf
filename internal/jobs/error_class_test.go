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
		"write tcp: broken pipe",
		"dial tcp: no route to host",
		"update error: transaction conflict. Please retry",
		"service temporarily unavailable",
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

func TestIsRetriableErrorEOFDoesNotOverMatch(t *testing.T) {
	// Real EOF errors are retriable...
	for _, s := range []string{"EOF", "unexpected EOF", "read tcp 10.0.0.1:8000: EOF"} {
		if !IsRetriableError(fmt.Errorf("%s", s)) {
			t.Errorf("IsRetriableError(%q) = false, want true", s)
		}
	}
	// ...but a word merely containing "eof" must NOT be classified retriable.
	for _, s := range []string{
		"invalid use of typeof in expression",
		"unsupported feof handler",
	} {
		if IsRetriableError(fmt.Errorf("%s", s)) {
			t.Errorf("IsRetriableError(%q) = true, want false (spurious eof match)", s)
		}
	}
}
