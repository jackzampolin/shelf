# 6. Pool-Based Worker Architecture

**Date:** 2025-12-19

**Status:** Accepted

## Decision

**All work flows through WorkerPools. One dispatcher owns the rate limiter.**

## Pool Types

| Pool Type | Pattern | Rate Limiting |
|-----------|---------|---------------|
| **ProviderWorkerPool** | Dispatcher → N workers | Single dispatcher goroutine |
| **CPUWorkerPool** | Shared queue → N workers | None (CPU-bound) |

## Why Pools, Not Individual Workers

The original design had N goroutines per provider, each calling `rateLimiter.Wait()`. This created contention - 30 goroutines competing for tokens.

The dispatcher pattern fixes this:
- **One dispatcher** owns the rate limiter, waits for tokens
- **N workers** execute requests without rate limit awareness
- **Clean separation** - dispatcher controls flow, workers do work

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│  ProviderWorkerPool "paddle"                            │
│                                                         │
│  ┌─────────┐    ┌─────────────┐    ┌───────────┐       │
│  │  Queue  │ →  │ Dispatcher  │ →  │ Work Chan │       │
│  └─────────┘    │ owns rate   │    └─────┬─────┘       │
│                 │ limiter     │          │             │
│                 └─────────────┘   ┌──────┴───────┐     │
│                                   │w1  w2  ...wN │     │
│                                   └──────┬───────┘     │
│                                          ↓             │
│                                    results chan        │
└─────────────────────────────────────────────────────────┘
```

## Key Types

```go
type WorkerPool interface {
    Name() string
    Type() PoolType
    Start(ctx context.Context)
    Submit(unit *WorkUnit) error
    Status() PoolStatus
}

type PoolStatus struct {
    Name        string `json:"name"`
    Type        string `json:"type"`
    Workers     int    `json:"workers"`
    InFlight    int    `json:"in_flight"`
    QueueDepth  int    `json:"queue_depth"`
    RateLimiter *providers.RateLimiterStatus `json:"rate_limiter,omitempty"`
}
```

## Scheduler Integration

```go
scheduler.RegisterPool(pool)     // Add a pool
scheduler.InitCPUPool(n)         // Create CPU pool with n workers
scheduler.InitFromRegistry(reg)  // Create pools from provider registry
scheduler.PoolStatuses()         // Get status of all pools
```

## Consequences

**Enables:** Clean rate limiting, consistent status reporting, predictable concurrency.

**Requires:** Understanding dispatcher pattern, pool lifecycle management.

## Core Principle

**One rate limiter owner. Many workers.**
