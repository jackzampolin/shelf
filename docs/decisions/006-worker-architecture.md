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

Each provider runs as a dedicated goroutine with its own rate limiter:

```go
type Worker interface {
    Run(ctx context.Context, jobs <-chan Job, results chan<- Result)
}

// Rate limiting per provider, not global
limiter := rate.NewLimiter(rate.Limit(provider.RateLimit), 1)
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
