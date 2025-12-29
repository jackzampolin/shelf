package jobs

import (
	"context"

	"github.com/jackzampolin/shelf/internal/providers"
)

// PoolType indicates what kind of work this pool handles.
type PoolType string

const (
	PoolTypeLLM PoolType = "llm"
	PoolTypeOCR PoolType = "ocr"
	PoolTypeCPU PoolType = "cpu"
)

// WorkerPool manages a pool of workers for a specific workload type.
// There are two implementations:
// - ProviderWorkerPool: For LLM/OCR providers with rate limiting
// - CPUWorkerPool: For CPU-bound tasks without rate limiting
type WorkerPool interface {
	// Name returns the pool name (e.g., "openrouter", "paddle", "cpu")
	Name() string

	// Type returns the pool type (llm, ocr, cpu)
	Type() PoolType

	// Start begins the pool's processing. Blocks until ctx cancelled.
	Start(ctx context.Context)

	// Submit adds a work unit to the pool's queue.
	// Returns error if queue is full.
	Submit(unit *WorkUnit) error

	// Status returns current pool status.
	Status() PoolStatus

	// init sets the results channel. Called by scheduler before Start.
	init(results chan<- workerResult)
}

// PoolStatus reports a pool's current state.
type PoolStatus struct {
	Name       string `json:"name"`
	Type       string `json:"type"`
	Workers    int    `json:"workers"`
	InFlight   int    `json:"in_flight"`
	QueueDepth int    `json:"queue_depth"`

	// Only for provider pools (nil for CPU)
	RateLimiter *providers.RateLimiterStatus `json:"rate_limiter,omitempty"`
}

// workerResult pairs a work result with its job ID for routing.
// Used internally by pools to send results to the scheduler.
type workerResult struct {
	JobID  string
	Unit   *WorkUnit
	Result WorkResult
}

// CPUTaskHandler processes a CPU work request and returns a result.
// Implementations should be safe for concurrent use.
type CPUTaskHandler func(ctx context.Context, req *CPUWorkRequest) (*CPUWorkResult, error)
