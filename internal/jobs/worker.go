package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"math/rand"
	"strings"
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

// ProviderWorker wraps a single provider (LLM or OCR) with rate limiting and concurrency control.
// Each worker owns its own input queue and runs a pool of goroutines up to MaxConcurrency.
// This allows saturating the provider's RPS limit while respecting concurrency bounds.
type ProviderWorker struct {
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

	// Concurrency control - max concurrent in-flight requests
	concurrency int
	semaphore   chan struct{}

	// Sink for async metrics writes (optional - if set, metrics are recorded automatically)
	sink *defra.Sink
}

// workerResult pairs a work result with its job ID for routing.
type workerResult struct {
	JobID  string
	Unit   *WorkUnit
	Result WorkResult
}

// ProviderWorkerConfig configures a new provider worker.
type ProviderWorkerConfig struct {
	Name   string
	Logger *slog.Logger

	// Set ONE of these
	LLMClient   providers.LLMClient
	OCRProvider providers.OCRProvider

	// Rate limiting (requests per second)
	// If 0, uses provider defaults
	RPS float64

	// Max concurrent in-flight requests
	// If 0, uses provider defaults (or DefaultMaxConcurrency)
	Concurrency int

	// Queue size for this worker (default 100)
	QueueSize int

	// Sink for async metrics writes (optional - enables automatic metrics recording)
	Sink *defra.Sink
}

// NewProviderWorker creates a new provider worker wrapping a provider.
func NewProviderWorker(cfg ProviderWorkerConfig) (*ProviderWorker, error) {
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
		queueSize = 10000 // Large queue to handle bulk book processing (10+ books)
	}

	w := &ProviderWorker{
		name:      cfg.Name,
		logger:    logger.With("worker", cfg.Name),
		queueSize: queueSize,
		sink:      cfg.Sink,
	}

	// Determine type, RPS, and concurrency - pull from provider if not overridden in config
	rps := cfg.RPS
	concurrency := cfg.Concurrency
	if cfg.LLMClient != nil {
		w.workerType = WorkerTypeLLM
		w.llmClient = cfg.LLMClient
		if rps == 0 {
			rps = cfg.LLMClient.RequestsPerSecond()
			if rps == 0 {
				rps = 1.0 // Fallback default
			}
		}
		if concurrency == 0 {
			concurrency = cfg.LLMClient.MaxConcurrency()
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
		if concurrency == 0 {
			concurrency = cfg.OCRProvider.MaxConcurrency()
		}
		if cfg.Name == "" {
			w.name = cfg.OCRProvider.Name()
		}
	}

	// Apply default concurrency if still 0
	if concurrency == 0 {
		concurrency = providers.DefaultMaxConcurrency
	}

	w.rateLimiter = providers.NewRateLimiter(rps)
	w.concurrency = concurrency
	w.logger = logger.With("worker", w.name, "type", w.workerType, "concurrency", concurrency)

	return w, nil
}

// Name returns the worker name.
func (w *ProviderWorker) Name() string {
	return w.name
}

// Type returns the worker type (LLM or OCR).
func (w *ProviderWorker) Type() WorkerType {
	return w.workerType
}

// init initializes the worker's queue, semaphore, and sets the results channel.
// Called by the scheduler before Start.
func (w *ProviderWorker) init(results chan<- workerResult) {
	w.queue = make(chan *WorkUnit, w.queueSize)
	w.semaphore = make(chan struct{}, w.concurrency)
	w.results = results
}

// Start runs the worker's processing loop with a concurrent goroutine pool.
// Spawns up to w.concurrency goroutines to process work units in parallel.
// Blocks until context is cancelled. Run in a goroutine.
func (w *ProviderWorker) Start(ctx context.Context) {
	w.logger.Info("worker started", "rps", w.rateLimiter.Status().RPS)

	for {
		select {
		case <-ctx.Done():
			w.logger.Info("worker stopping")
			return

		case unit := <-w.queue:
			// Acquire semaphore slot (blocks if at max concurrency)
			select {
			case w.semaphore <- struct{}{}:
				// Got a slot - spawn goroutine to process
				go func(u *WorkUnit) {
					defer func() { <-w.semaphore }() // Release slot when done

					result := w.Process(ctx, u)
					w.results <- workerResult{
						JobID:  u.JobID,
						Unit:   u,
						Result: result,
					}
				}(unit)

			case <-ctx.Done():
				w.logger.Info("worker stopping during semaphore wait")
				return
			}
		}
	}
}

// Submit adds a work unit to this worker's queue.
// Returns an error if the queue is full.
func (w *ProviderWorker) Submit(unit *WorkUnit) error {
	select {
	case w.queue <- unit:
		return nil
	default:
		return fmt.Errorf("%w: %s", ErrWorkerQueueFull, w.name)
	}
}

// QueueDepth returns the number of items in the worker's queue.
func (w *ProviderWorker) QueueDepth() int {
	return len(w.queue)
}

// Process executes a work unit and returns the result.
// This is also called internally by the worker's goroutine.
// Includes retry logic with exponential backoff for transient errors.
func (w *ProviderWorker) Process(ctx context.Context, unit *WorkUnit) WorkResult {
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

	// Get retry config from provider
	maxRetries := w.getMaxRetries()

	// Execute with retries
	var lastErr error
	for attempt := 0; attempt <= maxRetries; attempt++ {
		// Wait for rate limiter before each attempt
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
				lastErr = err
				if w.isRetriableError(err) && attempt < maxRetries {
					w.logger.Warn("LLM request failed, retrying",
						"unit_id", unit.ID,
						"attempt", attempt+1,
						"max_attempts", maxRetries+1,
						"error", err)
					w.sleepBeforeRetry(ctx, err, attempt)
					continue
				}
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
				lastErr = err
				if w.isRetriableError(err) && attempt < maxRetries {
					w.logger.Warn("OCR request failed, retrying",
						"unit_id", unit.ID,
						"attempt", attempt+1,
						"max_attempts", maxRetries+1,
						"error", err)
					w.sleepBeforeRetry(ctx, err, attempt)
					continue
				}
				result.Success = false
				result.Error = err
			} else {
				result.Success = ocrResult.Success
				if !ocrResult.Success {
					result.Error = fmt.Errorf("OCR failed: %s", ocrResult.ErrorMessage)
				}
			}
		}

		// If we got here without continuing, we're done (success or non-retriable error)
		break
	}

	// If we exhausted retries, set the last error
	if !result.Success && result.Error == nil && lastErr != nil {
		result.Error = fmt.Errorf("failed after %d attempts: %w", maxRetries+1, lastErr)
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

// getMaxRetries returns the max retry count from the underlying provider.
func (w *ProviderWorker) getMaxRetries() int {
	switch w.workerType {
	case WorkerTypeLLM:
		if w.llmClient != nil {
			return w.llmClient.MaxRetries()
		}
	case WorkerTypeOCR:
		if w.ocrProvider != nil {
			return w.ocrProvider.MaxRetries()
		}
	}
	// Default
	return 7
}

// isRetriableError checks if an error should trigger a retry.
// Also handles rate limit errors by notifying the rate limiter.
func (w *ProviderWorker) isRetriableError(err error) bool {
	if err == nil {
		return false
	}

	// Check for structured RateLimitError first
	if rle, ok := providers.IsRateLimitError(err); ok {
		// Notify rate limiter to drain tokens and back off
		w.rateLimiter.Record429(rle.RetryAfter)
		w.logger.Warn("rate limit hit, backing off",
			"retry_after", rle.RetryAfter)
		return true
	}

	errStr := err.Error()
	// Retry on 5xx errors (server errors)
	if strings.Contains(errStr, "status 500") ||
		strings.Contains(errStr, "status 502") ||
		strings.Contains(errStr, "status 503") ||
		strings.Contains(errStr, "status 504") {
		return true
	}
	// Retry on rate limit errors (fallback for providers without structured errors)
	if strings.Contains(errStr, "status 429") ||
		strings.Contains(errStr, "rate limit") {
		// Record 429 with default backoff since we don't have Retry-After
		w.rateLimiter.Record429(5 * time.Second)
		return true
	}
	// Retry on timeout errors
	if strings.Contains(errStr, "timeout") ||
		strings.Contains(errStr, "deadline exceeded") {
		return true
	}
	// Retry on connection errors
	if strings.Contains(errStr, "connection refused") ||
		strings.Contains(errStr, "connection reset") ||
		strings.Contains(errStr, "EOF") {
		return true
	}
	return false
}

// sleepBeforeRetry waits before retrying, using retry-after from rate limit errors
// or falling back to jitter-based delay.
func (w *ProviderWorker) sleepBeforeRetry(ctx context.Context, err error, attempt int) {
	var delay time.Duration

	// Check for rate limit error with Retry-After
	if rle, ok := providers.IsRateLimitError(err); ok && rle.RetryAfter > 0 {
		delay = rle.RetryAfter
		w.logger.Info("sleeping for Retry-After duration", "delay", delay)
	} else {
		// Use exponential backoff with jitter: base * 2^attempt + jitter
		base := time.Duration(1000) * time.Millisecond
		delay = base * time.Duration(1<<uint(attempt)) // 1s, 2s, 4s, 8s, 16s...
		jitter := time.Duration(rand.Intn(1000)) * time.Millisecond
		delay += jitter

		// Cap at 30 seconds
		if delay > 30*time.Second {
			delay = 30*time.Second + jitter
		}
	}

	select {
	case <-time.After(delay):
	case <-ctx.Done():
	}
}

// recordMetrics records metrics for a completed work unit via the sink.
func (w *ProviderWorker) recordMetrics(unit *WorkUnit, result *WorkResult) {
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
func (w *ProviderWorker) RateLimiterStatus() providers.RateLimiterStatus {
	return w.rateLimiter.Status()
}

// ConcurrencyStatus returns the current concurrency usage.
func (w *ProviderWorker) ConcurrencyStatus() (inFlight, max int) {
	return len(w.semaphore), w.concurrency
}
