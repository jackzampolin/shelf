# 7. Services Context Pattern

**Date:** 2025-12-17

**Status:** Accepted

## Decision

**Core services flow through context, not constructor injection.**

## The Problem

Many components need shared services (DefraClient, JobManager, Registry, Scheduler). Constructor injection leads to:
- Complex constructors with many parameters
- Difficulty adding new dependencies
- Inconsistent access patterns

## The Pattern

```go
// Server middleware enriches request context
ctx := svcctx.WithServices(r.Context(), services)

// Handlers extract what they need
jm := svcctx.JobManagerFrom(ctx)
jobs, _ := jm.List(ctx, filter)
```

Services struct created once at startup. Middleware injects into HTTP requests. Scheduler injects into job execution contexts.

## Available Extractors

```go
svcctx.DefraClientFrom(ctx)
svcctx.JobManagerFrom(ctx)
svcctx.RegistryFrom(ctx)
svcctx.SchedulerFrom(ctx)
svcctx.LoggerFrom(ctx)
```

## Why This Works

- **Uniform access** - Same pattern in handlers, jobs, workers
- **Easy to extend** - Add service to struct, available everywhere
- **Testable** - Build test context with mock services
- **No constructor churn** - Adding dependencies doesn't change signatures

## Core Principle

**Dependencies via context. Extract what you need.**
