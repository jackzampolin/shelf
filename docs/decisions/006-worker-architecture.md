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

## What This Enables

| Python (CLI) | Go (Jobs) |
|--------------|-----------|
| Run one stage, hope it works | Submit job, track progress |
| Ctrl+C loses progress | Graceful shutdown, resume |
| Check files to see status | Query DefraDB for status |
| Manual retry | Automatic retry with backoff |
| No visibility | Dashboard showing all work |

## Architecture

```
┌─────────┐     ┌─────────────┐     ┌──────────┐
│   API   │────▶│ Job Manager │────▶│ Workers  │
└─────────┘     └─────────────┘     └──────────┘
                      │                   │
                      ▼                   ▼
                 ┌─────────┐        ┌─────────┐
                 │ DefraDB │◀───────│ Results │
                 └─────────┘        └─────────┘
```

## Worker Pattern

Each provider is wrapped in a Worker with its own rate limiter:

```go
// Worker wraps a provider (LLM or OCR) with rate limiting
type Worker struct {
    llmClient   providers.LLMClient
    ocrProvider providers.OCRProvider
    rateLimiter *providers.RateLimiter
}

// Process executes a work unit, respecting rate limits
func (w *Worker) Process(ctx context.Context, unit *WorkUnit) WorkResult

// Providers define their own rate limits
type LLMClient interface {
    RequestsPerMinute() int  // RPM pulled at worker init
    MaxRetries() int
    RetryDelayBase() time.Duration
}
```

## Job Lifecycle

1. **Submit** - API creates job in DefraDB (status: pending)
2. **Assign** - Job manager assigns to worker
3. **Execute** - Worker processes, updates progress
4. **Complete** - Results written, status updated
5. **Query** - Full history available via GraphQL

## Core Principle

**Managed work > fire-and-forget commands.**

The server knows about all work. Nothing is invisible.
