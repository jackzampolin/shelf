package jobs

import (
	"context"
	"time"

	"github.com/jackzampolin/shelf/internal/providers"
)

// PoolType indicates what kind of work this pool handles.
type PoolType string

const (
	PoolTypeLLM PoolType = "llm"
	PoolTypeOCR PoolType = "ocr"
	PoolTypeTTS PoolType = "tts"
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

// JobWorkCanceller is implemented by pools that can discard queued/parked
// units for a cancelled job. In-flight provider calls may finish, but no queued
// unit should consume inference after cancellation.
type JobWorkCanceller interface {
	CancelJob(jobID string) int
}

// PoolJobWorkStatus locates one job's units within a provider pool. It makes a
// durable pending count operationally useful by distinguishing queued,
// claimed/in-flight, and provider-parked work.
type PoolJobWorkStatus struct {
	Queued   int `json:"queued"`
	InFlight int `json:"in_flight"`
	Parked   int `json:"parked"`
}

type JobWorkStatusProvider interface {
	JobWorkStatus(jobID string) PoolJobWorkStatus
}

// PoolStatus reports a pool's current state.
type PoolStatus struct {
	Name       string `json:"name"`
	Type       string `json:"type"`
	Workers    int    `json:"workers"`
	InFlight   int    `json:"in_flight"`
	QueueDepth int    `json:"queue_depth"`

	// Priority breakdown (nil for CPU pools)
	QueueByPriority *PriorityQueueStats `json:"queue_by_priority,omitempty"`

	// Only for provider pools (nil for CPU)
	RateLimiter *RateLimiterStatus `json:"rate_limiter,omitempty"`

	// Provider health circuit (provider pools only)
	Health      string                     `json:"health,omitempty"`
	ParkedUnits int                        `json:"parked_units,omitempty"`
	Endpoints   []providers.EndpointStatus `json:"endpoints,omitempty"`
}

// RateLimiterStatus mirrors providers.RateLimiterStatus for API responses.
// Keep fields in sync with internal/providers/ratelimit.go.
type RateLimiterStatus struct {
	TokensAvailable float64       `json:"tokens_available"`
	RPS             float64       `json:"rps"`
	Utilization     float64       `json:"utilization"`
	TimeUntilToken  time.Duration `json:"time_until_token"`
	TotalConsumed   int64         `json:"total_consumed"`
	TotalWaited     time.Duration `json:"total_waited"`
	Last429Time     time.Time     `json:"last_429_time,omitempty"`
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
