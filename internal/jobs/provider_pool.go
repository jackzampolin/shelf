package jobs

import (
	"context"
	"fmt"
	"log/slog"
	"math/rand"
	"strings"
	"sync/atomic"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/llmcall"
	"github.com/jackzampolin/shelf/internal/metrics"
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
		name: cfg.Name,
		sink: cfg.Sink,
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
			result := p.process(ctx, unit)
			p.inFlight.Add(-1)
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
	return p.queue.Push(unit)
}

// Status returns current pool status with priority queue breakdown.
func (p *ProviderWorkerPool) Status() PoolStatus {
	rlStatus := p.rateLimiter.Status()
	queueStats := p.queue.Stats()
	return PoolStatus{
		Name:            p.name,
		Type:            string(p.poolType),
		Workers:         p.workerCount,
		InFlight:        int(p.inFlight.Load()),
		QueueDepth:      queueStats.Total,
		QueueByPriority: &queueStats,
		RateLimiter:     toRateLimiterStatus(rlStatus),
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

// process executes a work unit with retry logic.
func (p *ProviderWorkerPool) process(ctx context.Context, unit *WorkUnit) WorkResult {
	result := WorkResult{
		WorkUnitID: unit.ID,
	}

	// Validate work unit type matches pool type
	if (unit.Type == WorkUnitTypeLLM && p.poolType != PoolTypeLLM) ||
		(unit.Type == WorkUnitTypeOCR && p.poolType != PoolTypeOCR) ||
		(unit.Type == WorkUnitTypeTTS && p.poolType != PoolTypeTTS) {
		result.Success = false
		result.Error = fmt.Errorf("work unit type %s does not match pool type %s", unit.Type, p.poolType)
		return result
	}

	maxRetries := p.getMaxRetries()
	var lastErr error

	for attempt := 0; attempt <= maxRetries; attempt++ {
		// Note: Rate limiting is handled by dispatcher, not here
		// Workers just execute as fast as they can

		switch p.poolType {
		case PoolTypeLLM:
			if unit.ChatRequest == nil {
				result.Success = false
				result.Error = fmt.Errorf("LLM work unit missing ChatRequest")
				return result
			}

			var chatResult *providers.ChatResult
			var err error

			if len(unit.Tools) > 0 {
				chatResult, err = p.llmClient.ChatWithTools(ctx, unit.ChatRequest, unit.Tools)
			} else {
				chatResult, err = p.llmClient.Chat(ctx, unit.ChatRequest)
			}

			result.ChatResult = chatResult
			if err != nil {
				lastErr = err
				if p.isRetriableError(err) && attempt < maxRetries {
					p.logger.Debug("LLM request failed, retrying",
						"unit_id", unit.ID,
						"attempt", attempt+1,
						"max_attempts", maxRetries+1,
						"error", err)
					p.sleepBeforeRetry(ctx, err, attempt)
					continue
				}
				result.Success = false
				result.Error = err
			} else {
				result.Success = chatResult.Success
				if !chatResult.Success {
					resultErr := fmt.Errorf("%s: %s", chatResult.ErrorType, chatResult.ErrorMessage)
					if p.isRetriableResultError(chatResult) && attempt < maxRetries {
						lastErr = resultErr
						p.logger.Debug("LLM result error, retrying",
							"unit_id", unit.ID,
							"attempt", attempt+1,
							"max_attempts", maxRetries+1,
							"error_type", chatResult.ErrorType)
						p.sleepBeforeRetry(ctx, resultErr, attempt)
						continue
					}
					result.Error = resultErr
				}
			}

		case PoolTypeOCR:
			if unit.OCRRequest == nil {
				result.Success = false
				result.Error = fmt.Errorf("OCR work unit missing OCRRequest")
				return result
			}

			ocrResult, err := p.ocrProvider.ProcessImage(ctx, unit.OCRRequest.Image, unit.OCRRequest.PageNum)
			result.OCRResult = ocrResult
			if err != nil {
				lastErr = err
				if p.isRetriableError(err) && attempt < maxRetries {
					p.logger.Debug("OCR request failed, retrying",
						"unit_id", unit.ID,
						"attempt", attempt+1,
						"max_attempts", maxRetries+1,
						"error", err)
					p.sleepBeforeRetry(ctx, err, attempt)
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

		case PoolTypeTTS:
			if unit.TTSRequest == nil {
				result.Success = false
				result.Error = fmt.Errorf("TTS work unit missing TTSRequest")
				return result
			}

			ttsReq := &providers.TTSRequest{
				Text:               unit.TTSRequest.Text,
				Voice:              unit.TTSRequest.Voice,
				Format:             unit.TTSRequest.Format,
				PreviousRequestIDs: unit.TTSRequest.PreviousRequestIDs, // For ElevenLabs request stitching
			}
			ttsResult, err := p.ttsProvider.Generate(ctx, ttsReq)
			result.TTSResult = ttsResult
			if err != nil {
				lastErr = err
				if p.isRetriableError(err) && attempt < maxRetries {
					p.logger.Debug("TTS request failed, retrying",
						"unit_id", unit.ID,
						"attempt", attempt+1,
						"max_attempts", maxRetries+1,
						"error", err)
					p.sleepBeforeRetry(ctx, err, attempt)
					continue
				}
				result.Success = false
				result.Error = err
			} else {
				result.Success = ttsResult.Success
				if !ttsResult.Success {
					result.Error = fmt.Errorf("TTS failed: %s", ttsResult.ErrorMessage)
				}
			}
		}

		// If we got here without continuing, we're done
		break
	}

	// If we exhausted retries, set the last error
	if !result.Success && result.Error == nil && lastErr != nil {
		result.Error = fmt.Errorf("failed after %d attempts: %w", maxRetries+1, lastErr)
	}

	// Record metrics
	p.recordMetrics(ctx, unit, &result)

	if result.Success {
		p.logger.Debug("work unit completed", "unit_id", unit.ID)
	} else {
		p.logger.Warn("work unit failed", "unit_id", unit.ID, "error", result.Error)
	}

	return result
}

func (p *ProviderWorkerPool) getMaxRetries() int {
	switch p.poolType {
	case PoolTypeLLM:
		if p.llmClient != nil {
			return p.llmClient.MaxRetries()
		}
	case PoolTypeOCR:
		if p.ocrProvider != nil {
			return p.ocrProvider.MaxRetries()
		}
	case PoolTypeTTS:
		if p.ttsProvider != nil {
			return p.ttsProvider.MaxRetries()
		}
	}
	return 7
}

func (p *ProviderWorkerPool) isRetriableError(err error) bool {
	if err == nil {
		return false
	}

	// Check for structured RateLimitError
	if rle, ok := providers.IsRateLimitError(err); ok {
		p.rateLimiter.Record429(rle.RetryAfter)
		p.logger.Debug("rate limit hit, backing off", "retry_after", rle.RetryAfter)
		return true
	}

	errStr := err.Error()
	if strings.Contains(errStr, "status 500") ||
		strings.Contains(errStr, "status 502") ||
		strings.Contains(errStr, "status 503") ||
		strings.Contains(errStr, "status 504") {
		return true
	}
	if strings.Contains(errStr, "status 429") ||
		strings.Contains(errStr, "rate limit") {
		p.rateLimiter.Record429(5 * time.Second)
		return true
	}
	if strings.Contains(errStr, "timeout") ||
		strings.Contains(errStr, "deadline exceeded") {
		return true
	}
	if strings.Contains(errStr, "connection refused") ||
		strings.Contains(errStr, "connection reset") ||
		strings.Contains(errStr, "EOF") {
		return true
	}
	return false
}

func (p *ProviderWorkerPool) isRetriableResultError(result *providers.ChatResult) bool {
	if result == nil {
		return false
	}
	return result.ErrorType == "json_parse"
}

func (p *ProviderWorkerPool) sleepBeforeRetry(ctx context.Context, err error, attempt int) {
	var delay time.Duration

	if rle, ok := providers.IsRateLimitError(err); ok && rle.RetryAfter > 0 {
		delay = rle.RetryAfter
		p.logger.Debug("sleeping for Retry-After duration", "delay", delay)
	} else {
		base := time.Duration(1000) * time.Millisecond
		delay = base * time.Duration(1<<uint(attempt))
		jitter := time.Duration(rand.Intn(1000)) * time.Millisecond
		delay += jitter

		if delay > 30*time.Second {
			delay = 30*time.Second + jitter
		}
	}

	select {
	case <-time.After(delay):
	case <-ctx.Done():
	}
}

func (p *ProviderWorkerPool) recordMetrics(ctx context.Context, unit *WorkUnit, result *WorkResult) {
	if p.sink == nil {
		p.logger.Debug("recordMetrics: sink not configured, metrics and LLM calls not recorded")
		return
	}
	if unit.Metrics == nil {
		p.logger.Debug("recordMetrics: unit.Metrics is nil, skipping", "unit_id", unit.ID)
		return
	}

	m := &metrics.Metric{
		JobID:     unit.JobID,
		BookID:    unit.Metrics.BookID,
		Stage:     unit.Metrics.Stage,
		ItemKey:   unit.Metrics.ItemKey,
		Success:   result.Success,
		CreatedAt: time.Now(),
	}

	switch p.poolType {
	case PoolTypeLLM:
		if result.ChatResult != nil {
			m.Provider = result.ChatResult.Provider
			m.Model = result.ChatResult.ModelUsed
			m.CostUSD = result.ChatResult.CostUSD
			m.PromptTokens = result.ChatResult.PromptTokens
			m.CompletionTokens = result.ChatResult.CompletionTokens
			m.ReasoningTokens = result.ChatResult.ReasoningTokens
			m.TotalTokens = result.ChatResult.TotalTokens
			// Add timing data
			m.QueueSeconds = result.ChatResult.QueueTime.Seconds()
			m.ExecutionSeconds = result.ChatResult.ExecutionTime.Seconds()
			m.TotalSeconds = result.ChatResult.TotalTime.Seconds()
			if !result.ChatResult.Success {
				m.ErrorType = result.ChatResult.ErrorType
			}
		}
	case PoolTypeOCR:
		if result.OCRResult != nil {
			m.Provider = p.name
			m.CostUSD = result.OCRResult.CostUSD
			// Add timing data
			m.ExecutionSeconds = result.OCRResult.ExecutionTime.Seconds()
			m.TotalSeconds = result.OCRResult.ExecutionTime.Seconds()
			if !result.OCRResult.Success {
				m.ErrorType = "ocr_error"
			}
		}
	case PoolTypeTTS:
		if result.TTSResult != nil {
			m.Provider = p.name
			m.CostUSD = result.TTSResult.CostUSD
			// Add timing data
			m.ExecutionSeconds = result.TTSResult.ExecutionTime.Seconds()
			m.TotalSeconds = result.TTSResult.ExecutionTime.Seconds()
			if !result.TTSResult.Success {
				m.ErrorType = "tts_error"
			}
		}
	}

	p.logger.Debug("recordMetrics: sending metric",
		"unit_id", unit.ID,
		"book_id", m.BookID,
		"stage", m.Stage,
		"cost_usd", m.CostUSD)

	if p.poolType == PoolTypeLLM {
		writeResult, err := p.sink.SendSync(ctx, defra.WriteOp{
			Op:         defra.OpCreate,
			Collection: "Metric",
			Document:   m.ToMap(),
		})
		if err != nil {
			p.logger.Warn("recordMetrics: failed to persist metric",
				"unit_id", unit.ID,
				"error", err)
		} else {
			result.MetricDocID = writeResult.DocID
		}
	} else {
		// Intentionally untracked: audit trail record, not mutable state.
		p.sink.Send(defra.WriteOp{
			Op:         defra.OpCreate,
			Collection: "Metric",
			Document:   m.ToMap(),
			Source:     "ProviderPool:recordMetric",
		})
	}

	// Also record LLM call for traceability (Phase 2)
	if p.poolType == PoolTypeLLM && result.ChatResult != nil {
		opts := llmcall.RecordOptions{
			BookID:    unit.Metrics.BookID,
			PageID:    unit.Metrics.PageID,
			JobID:     unit.JobID,
			PromptKey: unit.Metrics.PromptKey,
			PromptCID: unit.Metrics.PromptCID,
			Logger:    p.logger,
		}
		call := llmcall.FromChatResult(result.ChatResult, opts)
		if call != nil {
			// Intentionally untracked: audit trail record, not mutable state.
			p.sink.Send(defra.WriteOp{
				Op:         defra.OpCreate,
				Collection: "LLMCall",
				Document:   call.ToMap(),
				Source:     "ProviderPool:recordLLMCall",
			})
			p.logger.Debug("recordMetrics: recorded LLM call",
				"call_id", call.ID,
				"prompt_key", opts.PromptKey)
		}
	}
}

// Verify interface compliance
var _ WorkerPool = (*ProviderWorkerPool)(nil)
