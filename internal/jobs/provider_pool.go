package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/providers"
)

// ProviderWorkerPool manages a pool of workers for a single LLM, OCR, or TTS provider.
// Uses the dispatcher pattern: a single dispatcher goroutine owns the rate limiter
// and distributes work to N worker goroutines that execute without rate limit awareness.
// Work units are processed by priority (high priority first).
type ProviderWorkerPool struct {
	name     string
	poolType PoolType

	// Provider (one of these is set)
	llmClient   providers.LLMClient
	ocrProvider providers.OCRProvider
	ttsProvider providers.TTSProvider

	// Rate limiting (owned by dispatcher)
	rateLimiter *providers.RateLimiter

	// Logging
	logger *slog.Logger

	// Priority queue (jobs submit here)
	queue *PriorityQueue

	// Internal work channel (dispatcher -> workers)
	work chan *WorkUnit

	// Results channel (workers -> scheduler)
	results chan<- workerResult

	// Configuration
	workerCount int

	// In-flight tracking
	inFlight atomic.Int32

	// Health circuit breaker (see provider_pool_health.go)
	circuit *circuit

	// Provider wait state is reported back to the scheduler per affected job.
	waitMu        sync.Mutex
	waitingJobs   map[string]struct{}
	onWaitChange  func(provider, jobID string, waiting bool)
	cancelledJobs sync.Map

	// Metrics sink (optional)
	sink *defra.Sink
}

// ProviderWorkerPoolConfig configures a new provider worker pool.
type ProviderWorkerPoolConfig struct {
	Name   string
	Logger *slog.Logger

	// Set ONE of these
	LLMClient   providers.LLMClient
	OCRProvider providers.OCRProvider
	TTSProvider providers.TTSProvider

	// Rate limiting (requests per second)
	// If 0, uses provider defaults
	RPS float64

	// Number of worker goroutines
	// If 0, uses provider's MaxConcurrency or default (30)
	WorkerCount int

	// Sink for async metrics writes (optional)
	Sink *defra.Sink
}

// NewProviderWorkerPool creates a new provider worker pool.
func NewProviderWorkerPool(cfg ProviderWorkerPoolConfig) (*ProviderWorkerPool, error) {
	providerCount := 0
	if cfg.LLMClient != nil {
		providerCount++
	}
	if cfg.OCRProvider != nil {
		providerCount++
	}
	if cfg.TTSProvider != nil {
		providerCount++
	}
	if providerCount == 0 {
		return nil, fmt.Errorf("must provide LLMClient, OCRProvider, or TTSProvider")
	}
	if providerCount > 1 {
		return nil, fmt.Errorf("cannot provide multiple providers")
	}

	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	p := &ProviderWorkerPool{
		name:        cfg.Name,
		sink:        cfg.Sink,
		waitingJobs: make(map[string]struct{}),
	}

	// Determine type, RPS, and worker count from provider
	rps := cfg.RPS
	workerCount := cfg.WorkerCount

	if cfg.LLMClient != nil {
		p.poolType = PoolTypeLLM
		p.llmClient = cfg.LLMClient
		if rps == 0 {
			rps = cfg.LLMClient.RequestsPerSecond()
			if rps == 0 {
				rps = 1.0
			}
		}
		if workerCount == 0 {
			workerCount = cfg.LLMClient.MaxConcurrency()
		}
		if cfg.Name == "" {
			p.name = cfg.LLMClient.Name()
		}
	} else if cfg.OCRProvider != nil {
		p.poolType = PoolTypeOCR
		p.ocrProvider = cfg.OCRProvider
		if rps == 0 {
			rps = cfg.OCRProvider.RequestsPerSecond()
			if rps == 0 {
				rps = 1.0
			}
		}
		if workerCount == 0 {
			workerCount = cfg.OCRProvider.MaxConcurrency()
		}
		if cfg.Name == "" {
			p.name = cfg.OCRProvider.Name()
		}
	} else {
		p.poolType = PoolTypeTTS
		p.ttsProvider = cfg.TTSProvider
		if rps == 0 {
			rps = cfg.TTSProvider.RequestsPerSecond()
			if rps == 0 {
				rps = 1.0
			}
		}
		if workerCount == 0 {
			workerCount = cfg.TTSProvider.MaxConcurrency()
		}
		if cfg.Name == "" {
			p.name = cfg.TTSProvider.Name()
		}
	}

	if workerCount == 0 {
		workerCount = providers.DefaultMaxConcurrency
	}

	p.rateLimiter = providers.NewRateLimiter(rps)
	p.workerCount = workerCount
	p.circuit = &circuit{cfg: circuitConfig{
		TripThreshold: defaultCircuitTripThreshold,
		ProbeInterval: defaultCircuitProbeInterval,
		ParkMaxAge:    defaultParkMaxAge,
		ParkCapacity:  4 * workerCount,
	}}
	p.logger = logger.With("pool", p.name, "type", p.poolType, "workers", workerCount, "rps", rps)

	return p, nil
}

// Name returns the pool name.
func (p *ProviderWorkerPool) Name() string {
	return p.name
}

// Type returns the pool type.
func (p *ProviderWorkerPool) Type() PoolType {
	return p.poolType
}

// init initializes the priority queue and channels. Called by scheduler before Start.
func (p *ProviderWorkerPool) init(results chan<- workerResult) {
	p.queue = NewPriorityQueue()
	p.work = make(chan *WorkUnit, p.workerCount) // Buffered to avoid blocking dispatcher
	p.results = results
	p.logger.Debug("provider pool initialized")
}

// Start begins the pool's processing. Blocks until ctx cancelled.
func (p *ProviderWorkerPool) Start(ctx context.Context) {
	p.logger.Debug("provider pool started")

	// Start dispatcher (owns rate limiter)
	go p.dispatcher(ctx)

	// Start worker goroutines
	for i := 0; i < p.workerCount; i++ {
		go p.worker(ctx, i)
	}

	// Block until context cancelled
	<-ctx.Done()
	p.logger.Debug("provider pool stopping")
}

// dispatcher owns the rate limiter. Pulls from priority queue, waits for token, sends to work channel.
// Higher priority work units are processed first.
func (p *ProviderWorkerPool) dispatcher(ctx context.Context) {
	done := ctx.Done()
	for {
		// Pop blocks until an item is available or context is cancelled
		unit := p.queue.Pop(done)
		if unit == nil {
			// Context cancelled
			return
		}
		if p.jobCancelled(unit.JobID) {
			continue
		}

		// Pause while the provider circuit is open (see provider_pool_health.go).
		if ch := p.circuit.openWait(); ch != nil {
			p.markJobWaiting(unit.JobID)
			select {
			case <-ch:
				// Circuit closed; proceed with this unit.
			case <-ctx.Done():
				p.results <- workerResult{
					JobID: unit.JobID,
					Unit:  unit,
					Result: WorkResult{
						WorkUnitID: unit.ID,
						Success:    false,
						Error:      fmt.Errorf("circuit wait cancelled: %w", ctx.Err()),
					},
				}
				return
			}
		}

		// Wait for rate limit token (only dispatcher does this)
		if err := p.rateLimiter.Wait(ctx); err != nil {
			// Context cancelled, send failure result
			p.results <- workerResult{
				JobID: unit.JobID,
				Unit:  unit,
				Result: WorkResult{
					WorkUnitID: unit.ID,
					Success:    false,
					Error:      fmt.Errorf("rate limit wait cancelled: %w", err),
				},
			}
			continue
		}

		// Send to work channel for workers to pick up
		p.inFlight.Add(1)
		select {
		case p.work <- unit:
			// Sent successfully
		case <-ctx.Done():
			p.inFlight.Add(-1)
			return
		}
	}
}

// worker processes work units from the work channel.
func (p *ProviderWorkerPool) worker(ctx context.Context, id int) {
	for {
		select {
		case <-ctx.Done():
			return

		case unit, ok := <-p.work:
			// Handle channel close or nil unit
			if !ok || unit == nil {
				return
			}
			if p.jobCancelled(unit.JobID) {
				p.inFlight.Add(-1)
				continue
			}
			result, parked := p.process(ctx, unit)
			p.inFlight.Add(-1)
			if parked {
				// Unit is held by the circuit for replay; no result yet.
				continue
			}
			p.logger.Debug("worker sending result to scheduler",
				"unit_id", unit.ID,
				"job_id", unit.JobID,
				"unit_type", unit.Type,
				"success", result.Success,
				"has_ocr_result", result.OCRResult != nil,
			)
			p.results <- workerResult{
				JobID:  unit.JobID,
				Unit:   unit,
				Result: result,
			}
			p.logger.Debug("worker result sent", "unit_id", unit.ID, "unit_type", unit.Type)
		}
	}
}

// Submit adds a work unit to the pool's priority queue.
// Higher priority work units will be processed first.
// Returns an error if the pool is not initialized or unit is nil.
func (p *ProviderWorkerPool) Submit(unit *WorkUnit) error {
	if p.queue == nil {
		return fmt.Errorf("pool not initialized: call init() before Submit()")
	}
	p.cancelledJobs.Delete(unit.JobID)
	if err := p.queue.Push(unit); err != nil {
		return err
	}
	if p.circuit.isOpen() {
		p.markJobWaiting(unit.JobID)
	}
	return nil
}

// CancelJob purges queued and parked work and marks already-dispatched buffered
// units to be skipped by workers. Provider calls already in flight may finish.
func (p *ProviderWorkerPool) CancelJob(jobID string) int {
	if jobID == "" {
		return 0
	}
	p.cancelledJobs.Store(jobID, struct{}{})
	removed := 0
	if p.queue != nil {
		removed += p.queue.RemoveJob(jobID)
	}
	removed += p.circuit.removeJob(jobID)
	p.removeWaitingJob(jobID)
	return removed
}

func (p *ProviderWorkerPool) jobCancelled(jobID string) bool {
	_, cancelled := p.cancelledJobs.Load(jobID)
	return cancelled
}

// Status returns current pool status with priority queue breakdown.
func (p *ProviderWorkerPool) Status() PoolStatus {
	rlStatus := p.rateLimiter.Status()
	queueStats := p.queue.Stats()
	health, parkedCount := p.circuit.status()
	return PoolStatus{
		Name:            p.name,
		Type:            string(p.poolType),
		Workers:         p.workerCount,
		InFlight:        int(p.inFlight.Load()),
		QueueDepth:      queueStats.Total,
		QueueByPriority: &queueStats,
		RateLimiter:     toRateLimiterStatus(rlStatus),
		Health:          health,
		ParkedUnits:     parkedCount,
	}
}

func toRateLimiterStatus(status providers.RateLimiterStatus) *RateLimiterStatus {
	return &RateLimiterStatus{
		TokensAvailable: status.TokensAvailable,
		RPS:             status.RPS,
		Utilization:     status.Utilization,
		TimeUntilToken:  status.TimeUntilToken,
		TotalConsumed:   status.TotalConsumed,
		TotalWaited:     status.TotalWaited,
		Last429Time:     status.Last429Time,
	}
}

// Verify interface compliance
var _ WorkerPool = (*ProviderWorkerPool)(nil)
