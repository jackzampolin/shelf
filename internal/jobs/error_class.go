package jobs

import "strings"

// IsRetriableError reports whether err looks like a transient failure worth
// retrying. Deterministic errors such as 4xx validation failures return false
// so callers can fail fast instead of burning retries.
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
		strings.Contains(s, "connection closed"),
		strings.Contains(s, "broken pipe"),
		strings.Contains(s, "no route to host"),
		strings.Contains(s, "server misbehaving"),
		strings.Contains(s, "transaction conflict"),
		strings.Contains(s, "temporarily unavailable"),
		isEOFError(s):
		return true
	default:
		return false
	}
}

// isEOFError matches an EOF network error without over-matching unrelated words
// that merely contain "eof" (e.g. "typeof"). Go surfaces EOF as "EOF",
// "unexpected EOF", or wrapped like "read tcp ...: EOF".
func isEOFError(s string) bool {
	return s == "eof" ||
		strings.HasSuffix(s, " eof") ||
		strings.HasSuffix(s, ": eof") ||
		strings.Contains(s, "unexpected eof")
}
