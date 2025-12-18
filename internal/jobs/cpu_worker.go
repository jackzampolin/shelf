package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
)

const (
	WorkerTypeCPU WorkerType = "cpu"
)

// CPUTaskHandler processes a CPU work request and returns a result.
// Implementations should be safe for concurrent use.
type CPUTaskHandler func(ctx context.Context, req *CPUWorkRequest) (*CPUWorkResult, error)

// CPUWorker handles CPU-bound work without rate limiting.
// Unlike LLM/OCR workers, CPU workers don't wrap external providers.
// Instead, they execute registered task handlers.
type CPUWorker struct {
	name      string
	logger    *slog.Logger
	queueSize int

	// Queue for incoming work units (owned by this worker)
	queue chan *WorkUnit

	// Results channel (shared, set by scheduler)
	results chan<- workerResult

	// Task handlers by task name
	handlers map[string]CPUTaskHandler
	mu       sync.RWMutex
}

// CPUWorkerConfig configures a new CPU worker.
type CPUWorkerConfig struct {
	Name      string
	Logger    *slog.Logger
	QueueSize int // Default 100
}

// NewCPUWorker creates a new CPU worker.
func NewCPUWorker(cfg CPUWorkerConfig) *CPUWorker {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	queueSize := cfg.QueueSize
	if queueSize <= 0 {
		queueSize = 10000 // Large queue for CPU work (many pages per book)
	}

	name := cfg.Name
	if name == "" {
		name = "cpu"
	}

	return &CPUWorker{
		name:      name,
		logger:    logger.With("worker", name, "type", WorkerTypeCPU),
		queueSize: queueSize,
		handlers:  make(map[string]CPUTaskHandler),
	}
}

// RegisterHandler registers a handler for a task type.
// Must be called before Start.
func (w *CPUWorker) RegisterHandler(taskName string, handler CPUTaskHandler) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.handlers[taskName] = handler
	w.logger.Debug("registered CPU task handler", "task", taskName)
}

// Name returns the worker name.
func (w *CPUWorker) Name() string {
	return w.name
}

// Type returns WorkerTypeCPU.
func (w *CPUWorker) Type() WorkerType {
	return WorkerTypeCPU
}

// init initializes the worker's queue and sets the results channel.
// Called by the scheduler before Start.
func (w *CPUWorker) init(results chan<- workerResult) {
	w.queue = make(chan *WorkUnit, w.queueSize)
	w.results = results
}

// Start runs the worker's processing loop.
// Blocks until context is cancelled. Run in a goroutine.
func (w *CPUWorker) Start(ctx context.Context) {
	// Don't log individual worker starts - scheduler logs the count

	for {
		select {
		case <-ctx.Done():
			// Don't log individual worker stops - too noisy
			return

		case unit := <-w.queue:
			result := w.process(ctx, unit)
			w.results <- workerResult{
				JobID:  unit.JobID,
				Unit:   unit,
				Result: result,
			}
		}
	}
}

// Submit adds a work unit to this worker's queue.
// Returns an error if the queue is full.
func (w *CPUWorker) Submit(unit *WorkUnit) error {
	select {
	case w.queue <- unit:
		return nil
	default:
		return fmt.Errorf("%w: %s", ErrWorkerQueueFull, w.name)
	}
}

// QueueDepth returns the number of items in the worker's queue.
func (w *CPUWorker) QueueDepth() int {
	return len(w.queue)
}

// process executes a CPU work unit.
func (w *CPUWorker) process(ctx context.Context, unit *WorkUnit) WorkResult {
	result := WorkResult{
		WorkUnitID: unit.ID,
	}

	// Validate work unit type
	if unit.Type != WorkUnitTypeCPU {
		result.Success = false
		result.Error = fmt.Errorf("work unit type %s does not match worker type cpu", unit.Type)
		return result
	}

	if unit.CPURequest == nil {
		result.Success = false
		result.Error = fmt.Errorf("CPU work unit missing CPURequest")
		return result
	}

	// Find handler for this task
	w.mu.RLock()
	handler, ok := w.handlers[unit.CPURequest.Task]
	w.mu.RUnlock()

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
		w.logger.Debug("CPU work unit failed", "unit_id", unit.ID, "task", unit.CPURequest.Task, "error", err)
		return result
	}

	result.Success = true
	result.CPUResult = cpuResult
	w.logger.Debug("CPU work unit completed", "unit_id", unit.ID, "task", unit.CPURequest.Task)

	return result
}
