package jobs

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/jackzampolin/shelf/internal/providers"
)

// WorkerType indicates whether this worker handles LLM or OCR work.
type WorkerType string

const (
	WorkerTypeLLM WorkerType = "llm"
	WorkerTypeOCR WorkerType = "ocr"
)

// Worker wraps a single provider (LLM or OCR) with rate limiting.
type Worker struct {
	name        string
	workerType  WorkerType
	llmClient   providers.LLMClient
	ocrProvider providers.OCRProvider
	rateLimiter *providers.RateLimiter
	logger      *slog.Logger
}

// WorkerConfig configures a new worker.
type WorkerConfig struct {
	Name   string
	Logger *slog.Logger

	// Set ONE of these
	LLMClient   providers.LLMClient
	OCRProvider providers.OCRProvider

	// Rate limiting (requests per minute)
	// If 0, uses provider defaults or 60
	RPM int
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

	w := &Worker{
		name:   cfg.Name,
		logger: logger.With("worker", cfg.Name),
	}

	// Determine type and RPM - pull from provider if not overridden in config
	rpm := cfg.RPM
	if cfg.LLMClient != nil {
		w.workerType = WorkerTypeLLM
		w.llmClient = cfg.LLMClient
		if rpm == 0 {
			rpm = cfg.LLMClient.RequestsPerMinute()
			if rpm == 0 {
				rpm = 60 // Fallback default
			}
		}
		if cfg.Name == "" {
			w.name = cfg.LLMClient.Name()
		}
	} else {
		w.workerType = WorkerTypeOCR
		w.ocrProvider = cfg.OCRProvider
		if rpm == 0 {
			// Convert RPS to RPM
			rpm = int(cfg.OCRProvider.RequestsPerSecond() * 60)
			if rpm == 0 {
				rpm = 60 // Fallback default
			}
		}
		if cfg.Name == "" {
			w.name = cfg.OCRProvider.Name()
		}
	}

	w.rateLimiter = providers.NewRateLimiter(rpm)
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

// Process executes a work unit and returns the result.
// Blocks until rate limiter allows the request.
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
		chatResult, err := w.llmClient.Chat(ctx, unit.ChatRequest)
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

	// Log completion
	if result.Success {
		w.logger.Debug("work unit completed", "unit_id", unit.ID)
	} else {
		w.logger.Warn("work unit failed", "unit_id", unit.ID, "error", result.Error)
	}

	return result
}

// RateLimiterStatus returns the current rate limiter status.
func (w *Worker) RateLimiterStatus() providers.RateLimiterStatus {
	return w.rateLimiter.Status()
}
