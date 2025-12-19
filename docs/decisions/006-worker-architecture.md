# 6. Job-Based Worker Architecture

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**All work flows through a job system. Server manages jobs, not CLI.**

## Why Jobs

Python ran discrete CLI commands: `shelf.py book X stage Y run`. Each invocation was isolated. No central tracking. Hard to monitor, retry, or manage at scale.

Go uses a job system:
- **Trackable** - Every unit of work has an ID, status, history
- **Server-managed** - Submit via API, monitor via API, retry via API
- **Queryable** - "Show me all failed OCR jobs from today"
- **Resumable** - Server restarts don't lose work in progress

## Key Concepts

### Job

A Job represents a complete unit of work (e.g., "OCR this book", "correct these pages"). Jobs create WorkUnits dynamically and react to their completion.

```go
type Job interface {
    ID() string                    // DefraDB record ID
    SetRecordID(id string)         // Called after persistence
    Type() string                  // "ocr", "correct", etc.

    Start(ctx) ([]WorkUnit, error) // Create initial work units
    OnComplete(ctx, WorkResult) ([]WorkUnit, error) // React to completion
    Done() bool                    // All work finished?
    Status(ctx) (map[string]string, error)
}
```

### WorkUnit

A WorkUnit is a single API call - one LLM request or one OCR request.

```go
type WorkUnit struct {
    ID       string       // Unique identifier
    Type     WorkUnitType // "llm" or "ocr"
    Provider string       // Target specific provider, or "" for any
    JobID    string       // Parent job

    // One of these is set based on Type
    ChatRequest *providers.ChatRequest
    OCRRequest  *OCRWorkRequest
}
```

### ProviderWorker

A ProviderWorker wraps a single provider (LLMClient or OCRProvider) with rate limiting and a concurrency pool.

```go
type ProviderWorker struct {
    name        string
    workerType  WorkerType  // "llm" or "ocr"
    llmClient   providers.LLMClient
    ocrProvider providers.OCRProvider
    rateLimiter *providers.RateLimiter
    concurrency int         // max concurrent in-flight requests
    semaphore   chan struct{}
}

// Start runs the worker's processing loop with concurrent goroutines
func (w *ProviderWorker) Start(ctx context.Context)
```

Workers pull rate limits and concurrency from providers at initialization:
```go
// Providers define their own rate limits and concurrency
type LLMClient interface {
    RequestsPerSecond() float64
    MaxConcurrency() int  // max concurrent in-flight requests
    MaxRetries() int
    RetryDelayBase() time.Duration
}
```

### Scheduler

The Scheduler orchestrates everything: accepts jobs, queues work units, routes to workers, handles completion callbacks.

```go
scheduler.RegisterWorker(ocrWorker)
scheduler.RegisterWorker(llmWorker)
scheduler.Submit(ctx, job) // Persists to DefraDB, starts processing
```

## Architecture

```
┌─────────┐     ┌───────────┐     ┌──────────────┐
│   API   │────▶│ Scheduler │────▶│   Workers    │
└─────────┘     └───────────┘     │ (rate-limited)│
                     │            └──────────────┘
                     │                   │
              ┌──────▼──────┐            │
              │   Manager   │            │
              │ (persistence)│           │
              └──────┬──────┘            │
                     │                   │
                     ▼                   ▼
                ┌─────────┐        ┌──────────┐
                │ DefraDB │◀───────│ Results  │
                └─────────┘        └──────────┘
```

## Job Lifecycle

1. **Submit** - API calls `scheduler.Submit(job)`
2. **Persist** - Manager creates job record in DefraDB, sets job's record ID
3. **Start** - `job.Start()` returns initial WorkUnits
4. **Queue** - Scheduler queues WorkUnits
5. **Route** - Scheduler routes each WorkUnit to appropriate Worker
6. **Process** - Worker calls `Process()`, respects rate limits
7. **Complete** - Scheduler receives WorkResult, calls `job.OnComplete()`
8. **Chain** - OnComplete may return MORE WorkUnits (multi-phase jobs)
9. **Done** - When `job.Done()` returns true, status updated in DefraDB

## Multi-Phase Jobs

Jobs can implement multi-phase workflows via OnComplete:

```go
func (j *BookJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
    if result.OCRResult != nil {
        // OCR finished - now create LLM correction work
        return []WorkUnit{{
            Type: WorkUnitTypeLLM,
            ChatRequest: buildCorrectionPrompt(result.OCRResult.Text),
        }}, nil
    }
    return nil, nil // No follow-up work
}
```

## Core Principle

**Managed work > fire-and-forget commands.**

The server knows about all work. Nothing is invisible.
