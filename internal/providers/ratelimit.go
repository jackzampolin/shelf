package providers

import (
	"context"
	"sync"
	"time"
)

// RateLimiter implements a token bucket rate limiter.
// Matches the Python RateLimiter pattern.
type RateLimiter struct {
	mu sync.Mutex

	// Configuration
	requestsPerMinute int
	windowSeconds     float64

	// Token bucket state
	tokens     float64
	lastUpdate time.Time

	// Statistics
	totalConsumed int64
	totalWaited   time.Duration
	last429Time   time.Time
}

// RateLimiterStatus reports current limiter state.
type RateLimiterStatus struct {
	TokensAvailable  int           `json:"tokens_available"`
	TokensLimit      int           `json:"tokens_limit"`
	Utilization      float64       `json:"utilization"`
	TimeUntilToken   time.Duration `json:"time_until_token"`
	TotalConsumed    int64         `json:"total_consumed"`
	TotalWaited      time.Duration `json:"total_waited"`
	Last429Time      time.Time     `json:"last_429_time,omitempty"`
}

// NewRateLimiter creates a new rate limiter.
func NewRateLimiter(requestsPerMinute int) *RateLimiter {
	if requestsPerMinute <= 0 {
		requestsPerMinute = 150 // Default
	}
	return &RateLimiter{
		requestsPerMinute: requestsPerMinute,
		windowSeconds:     60.0,
		tokens:            float64(requestsPerMinute),
		lastUpdate:        time.Now(),
	}
}

// Wait blocks until a token is available or context is cancelled.
func (r *RateLimiter) Wait(ctx context.Context) error {
	for {
		r.mu.Lock()
		r.refill()

		if r.tokens >= 1.0 {
			r.tokens--
			r.totalConsumed++
			r.mu.Unlock()
			return nil
		}

		// Calculate wait time for next token
		tokensNeeded := 1.0 - r.tokens
		refillRate := float64(r.requestsPerMinute) / r.windowSeconds
		waitTime := time.Duration(tokensNeeded/refillRate*1000) * time.Millisecond
		r.mu.Unlock()

		// Wait outside lock
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-time.After(waitTime):
			r.mu.Lock()
			r.totalWaited += waitTime
			r.mu.Unlock()
		}
	}
}

// TryConsume attempts to consume a token without blocking.
// Returns true if successful, false if no tokens available.
func (r *RateLimiter) TryConsume() bool {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.refill()

	if r.tokens >= 1.0 {
		r.tokens--
		r.totalConsumed++
		return true
	}
	return false
}

// Record429 should be called when a 429 error is received.
// Optionally drains tokens if retryAfter is specified.
func (r *RateLimiter) Record429(retryAfter time.Duration) {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.last429Time = time.Now()
	if retryAfter > 0 {
		r.tokens = 0 // Drain all tokens
	}
}

// Status returns current limiter status.
func (r *RateLimiter) Status() RateLimiterStatus {
	r.mu.Lock()
	defer r.mu.Unlock()

	r.refill()

	utilization := 1.0 - (r.tokens / float64(r.requestsPerMinute))
	if utilization < 0 {
		utilization = 0
	}

	var timeUntilToken time.Duration
	if r.tokens < 1.0 {
		tokensNeeded := 1.0 - r.tokens
		refillRate := float64(r.requestsPerMinute) / r.windowSeconds
		timeUntilToken = time.Duration(tokensNeeded/refillRate*1000) * time.Millisecond
	}

	return RateLimiterStatus{
		TokensAvailable: int(r.tokens),
		TokensLimit:     r.requestsPerMinute,
		Utilization:     utilization,
		TimeUntilToken:  timeUntilToken,
		TotalConsumed:   r.totalConsumed,
		TotalWaited:     r.totalWaited,
		Last429Time:     r.last429Time,
	}
}

// refill adds tokens based on elapsed time. Must be called with lock held.
func (r *RateLimiter) refill() {
	now := time.Now()
	elapsed := now.Sub(r.lastUpdate).Seconds()
	r.lastUpdate = now

	// Add tokens based on elapsed time
	refillRate := float64(r.requestsPerMinute) / r.windowSeconds
	r.tokens += elapsed * refillRate

	// Cap at max
	if r.tokens > float64(r.requestsPerMinute) {
		r.tokens = float64(r.requestsPerMinute)
	}
}
