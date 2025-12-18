package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/providers"
)

// WorkerType indicates what kind of work this worker handles.
type WorkerType string

const (
	WorkerTypeLLM WorkerType = "llm"
	WorkerTypeOCR WorkerType = "ocr"
)

// WorkerInterface is implemented by all worker types.
// This allows the scheduler to manage different worker implementations uniformly.
type WorkerInterface interface {
	Name() string
	Type() WorkerType
	Start(ctx context.Context)
	Submit(unit *WorkUnit) error
	QueueDepth() int
	init(results chan<- workerResult)
}

// Worker wraps a single provider (LLM or OCR) with rate limiting.
// Each worker owns its own input queue and runs as a single goroutine.
// This ensures rate limiting is properly enforced per-provider.
type Worker struct {
	name        string
	workerType  WorkerType
	llmClient   providers.LLMClient
	ocrProvider providers.OCRProvider
	rateLimiter *providers.RateLimiter
	logger      *slog.Logger

	// Queue for incoming work units (owned by this worker)
	queue chan *WorkUnit

	// Results channel (shared, set by scheduler)
	results chan<- workerResult

	// Queue size configuration
	queueSize int

	// Sink for async metrics writes (optional - if set, metrics are recorded automatically)
	sink *defra.Sink
}

// workerResult pairs a work result with its job ID for routing.
type workerResult struct {
	JobID  string
	Unit   *WorkUnit
	Result WorkResult
}

// WorkerConfig configures a new worker.
type WorkerConfig struct {
	Name   string
	Logger *slog.Logger

	// Set ONE of these
	LLMClient   providers.LLMClient
	OCRProvider providers.OCRProvider

	// Rate limiting (requests per second)
	// If 0, uses provider defaults
	RPS float64

	// Queue size for this worker (default 100)
	QueueSize int

	// Sink for async metrics writes (optional - enables automatic metrics recording)
	Sink *defra.Sink
}

// NewWorker creates a new worker wrapping a provider.
func NewWorker(cfg WorkerConfig) (*Worker, error) {
	if cfg.LLMClient == nil && cfg.OCRProvider == nil {
		return nil, fmt.Errorf("must provide either LLMClient or OCRProvider")
	}
	if cfg.LLMClient != nil && cfg.OCRProvider != nil {
		return nil, fmt.Errorf("cannot provide both LLMClient and OCRProvider")
	}

	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	queueSize := cfg.QueueSize
	if queueSize <= 0 {
		queueSize = 100
	}

	w := &Worker{
		name:      cfg.Name,
		logger:    logger.With("worker", cfg.Name),
		queueSize: queueSize,
		sink:      cfg.Sink,
	}

	// Determine type and RPS - pull from provider if not overridden in config
	rps := cfg.RPS
	if cfg.LLMClient != nil {
		w.workerType = WorkerTypeLLM
		w.llmClient = cfg.LLMClient
		if rps == 0 {
			rps = cfg.LLMClient.RequestsPerSecond()
			if rps == 0 {
				rps = 1.0 // Fallback default
			}
		}
		if cfg.Name == "" {
			w.name = cfg.LLMClient.Name()
		}
	} else {
		w.workerType = WorkerTypeOCR
		w.ocrProvider = cfg.OCRProvider
		if rps == 0 {
			rps = cfg.OCRProvider.RequestsPerSecond()
			if rps == 0 {
				rps = 1.0 // Fallback default
			}
		}
		if cfg.Name == "" {
			w.name = cfg.OCRProvider.Name()
		}
	}

	w.rateLimiter = providers.NewRateLimiter(rps)
	w.logger = logger.With("worker", w.name, "type", w.workerType)

	return w, nil
}

// Name returns the worker name.
func (w *Worker) Name() string {
	return w.name
}

// Type returns the worker type (LLM or OCR).
func (w *Worker) Type() WorkerType {
	return w.workerType
}

// init initializes the worker's queue and sets the results channel.
// Called by the scheduler before Start.
func (w *Worker) init(results chan<- workerResult) {
	w.queue = make(chan *WorkUnit, w.queueSize)
	w.results = results
}

// Start runs the worker's processing loop.
// Blocks until context is cancelled. Run in a goroutine.
func (w *Worker) Start(ctx context.Context) {
	w.logger.Info("worker started")

	for {
		select {
		case <-ctx.Done():
			w.logger.Info("worker stopping")
			return

		case unit := <-w.queue:
			result := w.Process(ctx, unit)
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
func (w *Worker) Submit(unit *WorkUnit) error {
	select {
	case w.queue <- unit:
		return nil
	default:
		return fmt.Errorf("%w: %s", ErrWorkerQueueFull, w.name)
	}
}

// QueueDepth returns the number of items in the worker's queue.
func (w *Worker) QueueDepth() int {
	return len(w.queue)
}

// Process executes a work unit and returns the result.
// This is also called internally by the worker's goroutine.
func (w *Worker) Process(ctx context.Context, unit *WorkUnit) WorkResult {
	result := WorkResult{
		WorkUnitID: unit.ID,
	}

	// Validate work unit type matches worker type
	if (unit.Type == WorkUnitTypeLLM && w.workerType != WorkerTypeLLM) ||
		(unit.Type == WorkUnitTypeOCR && w.workerType != WorkerTypeOCR) {
		result.Success = false
		result.Error = fmt.Errorf("work unit type %s does not match worker type %s", unit.Type, w.workerType)
		return result
	}

	// Wait for rate limiter
	if err := w.rateLimiter.Wait(ctx); err != nil {
		result.Success = false
		result.Error = fmt.Errorf("rate limit wait failed: %w", err)
		return result
	}

	// Execute based on type
	switch w.workerType {
	case WorkerTypeLLM:
		if unit.ChatRequest == nil {
			result.Success = false
			result.Error = fmt.Errorf("LLM work unit missing ChatRequest")
			return result
		}

		var chatResult *providers.ChatResult
		var err error

		// Use ChatWithTools if tools are provided
		if len(unit.Tools) > 0 {
			chatResult, err = w.llmClient.ChatWithTools(ctx, unit.ChatRequest, unit.Tools)
		} else {
			chatResult, err = w.llmClient.Chat(ctx, unit.ChatRequest)
		}

		result.ChatResult = chatResult
		if err != nil {
			result.Success = false
			result.Error = err
		} else {
			result.Success = chatResult.Success
			if !chatResult.Success {
				result.Error = fmt.Errorf("%s: %s", chatResult.ErrorType, chatResult.ErrorMessage)
			}
		}

	case WorkerTypeOCR:
		if unit.OCRRequest == nil {
			result.Success = false
			result.Error = fmt.Errorf("OCR work unit missing OCRRequest")
			return result
		}
		ocrResult, err := w.ocrProvider.ProcessImage(ctx, unit.OCRRequest.Image, unit.OCRRequest.PageNum)
		result.OCRResult = ocrResult
		if err != nil {
			result.Success = false
			result.Error = err
		} else {
			result.Success = ocrResult.Success
			if !ocrResult.Success {
				result.Error = fmt.Errorf("OCR failed: %s", ocrResult.ErrorMessage)
			}
		}
	}

	// Record metrics (if sink is configured and unit has metrics attribution)
	w.recordMetrics(unit, &result)

	// Log completion
	if result.Success {
		w.logger.Debug("work unit completed", "unit_id", unit.ID)
	} else {
		w.logger.Warn("work unit failed", "unit_id", unit.ID, "error", result.Error)
	}

	return result
}

// recordMetrics records metrics for a completed work unit via the sink.
func (w *Worker) recordMetrics(unit *WorkUnit, result *WorkResult) {
	if w.sink == nil || unit.Metrics == nil {
		return
	}

	// Build metric inline based on result type
	m := &metrics.Metric{
		JobID:     unit.JobID,
		BookID:    unit.Metrics.BookID,
		Stage:     unit.Metrics.Stage,
		ItemKey:   unit.Metrics.ItemKey,
		Success:   result.Success,
		CreatedAt: time.Now(),
	}

	switch w.workerType {
	case WorkerTypeLLM:
		if result.ChatResult != nil {
			m.Provider = result.ChatResult.Provider
			m.Model = result.ChatResult.ModelUsed
			m.CostUSD = result.ChatResult.CostUSD
			m.PromptTokens = result.ChatResult.PromptTokens
			m.CompletionTokens = result.ChatResult.CompletionTokens
			m.ReasoningTokens = result.ChatResult.ReasoningTokens
			m.TotalTokens = result.ChatResult.TotalTokens
			if !result.ChatResult.Success {
				m.ErrorType = result.ChatResult.ErrorType
			}
		}
	case WorkerTypeOCR:
		if result.OCRResult != nil {
			m.Provider = w.name
			if !result.OCRResult.Success {
				m.ErrorType = "ocr_error"
			}
		}
	}

	// Fire-and-forget via sink
	w.sink.Send(defra.WriteOp{
		Op:         defra.OpCreate,
		Collection: "Metric",
		Document:   m.ToMap(),
	})
}

// RateLimiterStatus returns the current rate limiter status.
func (w *Worker) RateLimiterStatus() providers.RateLimiterStatus {
	return w.rateLimiter.Status()
}
