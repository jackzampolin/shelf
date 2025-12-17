package providers

import (
	"context"
	"sync"
	"time"
)

// RateLimiter implements a token bucket rate limiter.
// Uses requests per second (RPS) as the rate unit.
type RateLimiter struct {
	mu sync.Mutex

	// Configuration - requests per second
	rps float64

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
	TokensAvailable float64       `json:"tokens_available"`
	RPS             float64       `json:"rps"`
	Utilization     float64       `json:"utilization"`
	TimeUntilToken  time.Duration `json:"time_until_token"`
	TotalConsumed   int64         `json:"total_consumed"`
	TotalWaited     time.Duration `json:"total_waited"`
	Last429Time     time.Time     `json:"last_429_time,omitempty"`
}

// NewRateLimiter creates a new rate limiter with the given requests per second.
func NewRateLimiter(rps float64) *RateLimiter {
	if rps <= 0 {
		rps = 1.0 // Conservative default
	}
	return &RateLimiter{
		rps:        rps,
		tokens:     rps, // Start with 1 second worth of tokens
		lastUpdate: time.Now(),
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
		waitTime := time.Duration(tokensNeeded/r.rps*1000) * time.Millisecond
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

	utilization := 1.0 - (r.tokens / r.rps)
	if utilization < 0 {
		utilization = 0
	}

	var timeUntilToken time.Duration
	if r.tokens < 1.0 {
		tokensNeeded := 1.0 - r.tokens
		timeUntilToken = time.Duration(tokensNeeded/r.rps*1000) * time.Millisecond
	}

	return RateLimiterStatus{
		TokensAvailable: r.tokens,
		RPS:             r.rps,
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

	// Add tokens based on elapsed time (rps tokens per second)
	r.tokens += elapsed * r.rps

	// Cap at max (1 second worth of tokens)
	if r.tokens > r.rps {
		r.tokens = r.rps
	}
}
