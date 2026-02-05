package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"sync/atomic"
)

// CPUWorkerPool manages a pool of workers for CPU-bound tasks.
// All workers share a single queue - natural load balancing via Go channel semantics.
// No rate limiting since CPU work doesn't hit external APIs.
type CPUWorkerPool struct {
	name        string
	logger      *slog.Logger
	workerCount int
	queueSize   int

	// Single shared queue (all workers pull from this)
	queue chan *WorkUnit

	// Results channel (workers -> scheduler)
	results chan<- workerResult

	// Task handlers by task name
	handlers map[string]CPUTaskHandler
	mu       sync.RWMutex

	// In-flight tracking
	inFlight atomic.Int32
}

// CPUWorkerPoolConfig configures a new CPU worker pool.
type CPUWorkerPoolConfig struct {
	Name        string
	Logger      *slog.Logger
	WorkerCount int // Number of worker goroutines (default: runtime.NumCPU())
	QueueSize   int // Queue size (default: 10000)
}

// NewCPUWorkerPool creates a new CPU worker pool.
func NewCPUWorkerPool(cfg CPUWorkerPoolConfig) *CPUWorkerPool {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	name := cfg.Name
	if name == "" {
		name = "cpu"
	}

	queueSize := cfg.QueueSize
	if queueSize <= 0 {
		queueSize = 10000
	}

	workerCount := cfg.WorkerCount
	if workerCount <= 0 {
		workerCount = 1 // Will be set by caller typically
	}

	return &CPUWorkerPool{
		name:        name,
		logger:      logger.With("pool", name, "type", PoolTypeCPU, "workers", workerCount),
		workerCount: workerCount,
		queueSize:   queueSize,
		handlers:    make(map[string]CPUTaskHandler),
	}
}

// RegisterHandler registers a handler for a task type.
// Must be called before Start.
func (p *CPUWorkerPool) RegisterHandler(taskName string, handler CPUTaskHandler) {
	p.mu.Lock()
	defer p.mu.Unlock()
	p.handlers[taskName] = handler
	p.logger.Debug("registered CPU task handler", "task", taskName)
}

// Name returns the pool name.
func (p *CPUWorkerPool) Name() string {
	return p.name
}

// Type returns PoolTypeCPU.
func (p *CPUWorkerPool) Type() PoolType {
	return PoolTypeCPU
}

// init initializes channels. Called by scheduler before Start.
func (p *CPUWorkerPool) init(results chan<- workerResult) {
	p.queue = make(chan *WorkUnit, p.queueSize)
	p.results = results
	p.logger.Info("cpu pool init called", "results_channel_ptr", fmt.Sprintf("%p", results))
}

// Start begins the pool's processing. Blocks until ctx cancelled.
func (p *CPUWorkerPool) Start(ctx context.Context) {
	p.logger.Info("cpu pool starting", "queue_nil", p.queue == nil, "results_nil", p.results == nil)

	// Start worker goroutines - all pull from same queue
	for i := 0; i < p.workerCount; i++ {
		go p.worker(ctx, i)
	}

	// Block until context cancelled
	<-ctx.Done()
	p.logger.Info("pool stopping")
}

// worker processes work units from the shared queue.
func (p *CPUWorkerPool) worker(ctx context.Context, id int) {
	p.logger.Debug("cpu worker started", "worker_id", id)
	for {
		select {
		case <-ctx.Done():
			return

		case unit := <-p.queue:
			p.logger.Debug("cpu worker received unit", "worker_id", id, "unit_id", unit.ID, "job_id", unit.JobID)
			p.inFlight.Add(1)
			result := p.process(ctx, unit)
			p.inFlight.Add(-1)
			p.logger.Debug("cpu worker completed unit", "worker_id", id, "unit_id", unit.ID, "success", result.Success)
			p.results <- workerResult{
				JobID:  unit.JobID,
				Unit:   unit,
				Result: result,
			}
		}
	}
}

// Submit adds a work unit to the pool's queue.
func (p *CPUWorkerPool) Submit(unit *WorkUnit) error {
	select {
	case p.queue <- unit:
		p.logger.Debug("cpu pool accepted unit", "unit_id", unit.ID, "job_id", unit.JobID, "queue_len", len(p.queue))
		return nil
	default:
		p.logger.Warn("cpu pool queue full", "unit_id", unit.ID, "job_id", unit.JobID)
		return fmt.Errorf("%w: %s", ErrWorkerQueueFull, p.name)
	}
}

// Status returns current pool status.
func (p *CPUWorkerPool) Status() PoolStatus {
	return PoolStatus{
		Name:        p.name,
		Type:        string(PoolTypeCPU),
		Workers:     p.workerCount,
		InFlight:    int(p.inFlight.Load()),
		QueueDepth:  len(p.queue),
		RateLimiter: nil, // CPU pool has no rate limiter
	}
}

// process executes a CPU work unit.
func (p *CPUWorkerPool) process(ctx context.Context, unit *WorkUnit) WorkResult {
	result := WorkResult{
		WorkUnitID: unit.ID,
	}

	// Validate work unit type
	if unit.Type != WorkUnitTypeCPU {
		result.Success = false
		result.Error = fmt.Errorf("work unit type %s does not match pool type cpu", unit.Type)
		return result
	}

	if unit.CPURequest == nil {
		result.Success = false
		result.Error = fmt.Errorf("CPU work unit missing CPURequest")
		return result
	}

	// Find handler for this task
	p.mu.RLock()
	handler, ok := p.handlers[unit.CPURequest.Task]
	p.mu.RUnlock()

	if !ok {
		result.Success = false
		result.Error = fmt.Errorf("no handler registered for CPU task: %s", unit.CPURequest.Task)
		return result
	}

	// Execute handler (no rate limiting for CPU work)
	cpuResult, err := handler(ctx, unit.CPURequest)
	if err != nil {
		result.Success = false
		result.Error = err
		p.logger.Debug("CPU work unit failed", "unit_id", unit.ID, "task", unit.CPURequest.Task, "error", err)
		return result
	}

	result.Success = true
	result.CPUResult = cpuResult
	p.logger.Debug("CPU work unit completed", "unit_id", unit.ID, "task", unit.CPURequest.Task)

	return result
}

// Verify interface compliance
var _ WorkerPool = (*CPUWorkerPool)(nil)
