package jobs

import (
	"context"
	"fmt"
	"math/rand"
	"strings"
	"time"

	"github.com/jackzampolin/shelf/internal/defra"
	"github.com/jackzampolin/shelf/internal/llmcall"
	"github.com/jackzampolin/shelf/internal/metrics"
	"github.com/jackzampolin/shelf/internal/providers"
)

// process executes a work unit with retry logic. The second return value
// reports that the unit was parked by the health circuit for later replay:
// no result may be delivered for it yet.
func (p *ProviderWorkerPool) process(ctx context.Context, unit *WorkUnit) (WorkResult, bool) {
	result := WorkResult{
		WorkUnitID: unit.ID,
	}

	// Validate work unit type matches pool type
	if (unit.Type == WorkUnitTypeLLM && p.poolType != PoolTypeLLM) ||
		(unit.Type == WorkUnitTypeOCR && p.poolType != PoolTypeOCR) ||
		(unit.Type == WorkUnitTypeTTS && p.poolType != PoolTypeTTS) {
		result.Success = false
		result.Error = fmt.Errorf("work unit type %s does not match pool type %s", unit.Type, p.poolType)
		return result, false
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
				return result, false
			}

			var chatResult *providers.ChatResult
			var err error

			if len(unit.Tools) > 0 {
				chatResult, err = p.llmClient.ChatWithTools(ctx, unit.ChatRequest, unit.Tools)
			} else {
				chatResult, err = p.llmClient.Chat(ctx, unit.ChatRequest)
			}

			result.ChatResult = chatResult
			if err == nil {
				p.noteCallSuccess()
			}
			if err != nil {
				lastErr = err
				if p.isRetriableError(err) && attempt < maxRetries {
					p.noteInfraFailure(ctx, unit.JobID)
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
				return result, false
			}

			ocrResult, err := p.ocrProvider.ProcessImage(ctx, unit.OCRRequest.Image, unit.OCRRequest.PageNum)
			result.OCRResult = ocrResult
			if err == nil {
				p.noteCallSuccess()
			}
			if err != nil {
				lastErr = err
				if p.isRetriableError(err) && attempt < maxRetries {
					p.noteInfraFailure(ctx, unit.JobID)
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
				return result, false
			}

			ttsReq := &providers.TTSRequest{
				Text:               unit.TTSRequest.Text,
				Voice:              unit.TTSRequest.Voice,
				Format:             unit.TTSRequest.Format,
				Instructions:       unit.TTSRequest.Instructions,
				PreviousRequestIDs: unit.TTSRequest.PreviousRequestIDs, // For ElevenLabs request stitching
			}
			ttsResult, err := p.ttsProvider.Generate(ctx, ttsReq)
			result.TTSResult = ttsResult
			if err == nil {
				p.noteCallSuccess()
			}
			if err != nil {
				lastErr = err
				if p.isRetriableError(err) && attempt < maxRetries {
					p.noteInfraFailure(ctx, unit.JobID)
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

	// Park-and-replay: a unit whose final failure is infra-class while the
	// circuit is open — including the failure that trips it (atomic check) —
	// waits for backend recovery instead of failing through to its job. Its
	// metric is recorded at the final outcome (replay or park expiry).
	if !result.Success {
		parked, justTripped := p.circuit.noteFinalFailure(unit, result.Error)
		if justTripped {
			p.onCircuitOpen(ctx, unit.JobID)
		}
		if parked {
			p.markJobWaiting(unit.JobID)
			p.logger.Warn("work unit parked pending provider recovery",
				"unit_id", unit.ID, "error", result.Error)
			return result, true
		}
	}

	// Record metrics
	p.recordMetrics(ctx, unit, &result)

	if result.Success {
		p.logger.Debug("work unit completed", "unit_id", unit.ID)
	} else {
		p.logger.Warn("work unit failed", "unit_id", unit.ID, "error", result.Error)
	}

	return result, false
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

	// Structured rate-limit error carries a precise RetryAfter.
	if rle, ok := providers.IsRateLimitError(err); ok {
		p.rateLimiter.Record429(rle.RetryAfter)
		p.logger.Debug("rate limit hit, backing off", "retry_after", rle.RetryAfter)
		return true
	}

	// Record a coarse 429 backoff before delegating classification.
	errStr := strings.ToLower(err.Error())
	if strings.Contains(errStr, "status 429") ||
		strings.Contains(errStr, "rate limit") {
		p.rateLimiter.Record429(5 * time.Second)
	}

	return IsRetriableError(err)
}

func (p *ProviderWorkerPool) isRetriableResultError(result *providers.ChatResult) bool {
	if result == nil {
		return false
	}
	return result.ErrorType == "json_parse" || result.ErrorType == "schema_validation"
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
