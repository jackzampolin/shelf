# 7. Services Context Pattern

**Date:** 2025-12-17

**Status:** Accepted

## Decision

**Core services flow through context, not constructor injection.**

All components (HTTP handlers, jobs, workers) access shared services via context extraction rather than struct fields.

## Motivation

The codebase has several core services that many components need:

- **DefraClient** - Database queries
- **DefraSink** - Batched writes (#123)
- **JobManager** - Job persistence
- **Registry** - Provider access
- **Scheduler** - Work distribution

Currently these are wired via constructor injection, leading to:
- Complex constructors with many parameters
- Difficulty adding new dependencies
- Inconsistent access patterns across components

## Design

### Services Struct

```go
// internal/server/services.go

type Services struct {
    DefraClient *defra.Client
    DefraSink   *defra.Sink       // From #123
    JobManager  *jobs.Manager
    Registry    *providers.Registry
    Scheduler   *jobs.Scheduler
    Logger      *slog.Logger
}

type servicesKey struct{}

func WithServices(ctx context.Context, s *Services) context.Context {
    return context.WithValue(ctx, servicesKey{}, s)
}

func ServicesFrom(ctx context.Context) *Services {
    s, _ := ctx.Value(servicesKey{}).(*Services)
    return s
}
```

### HTTP Handlers

Server middleware enriches every request:

```go
func (s *Server) withServices(next http.HandlerFunc) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        ctx := WithServices(r.Context(), s.services)
        next(w, r.WithContext(ctx))
    }
}
```

Handlers extract what they need:

```go
func (e *ListJobsEndpoint) handler(w http.ResponseWriter, r *http.Request) {
    svc := ServicesFrom(r.Context())
    jobs, err := svc.JobManager.List(r.Context(), filter)
    // ...
}
```

### Job Execution

Scheduler enriches context before calling job methods:

```go
// In Scheduler.Submit
func (s *Scheduler) Submit(ctx context.Context, job Job) error {
    ctx = WithServices(ctx, s.services)
    units, err := job.Start(ctx)
    // ...
}

// In Scheduler.handleResult
func (s *Scheduler) handleResult(ctx context.Context, wr workerResult) {
    ctx = WithServices(ctx, s.services)
    newUnits, err := job.OnComplete(ctx, wr.Result)
    // ...
}
```

Jobs access services naturally:

```go
func (j *OcrJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
    svc := ServicesFrom(ctx)

    // Write OCR result via sink
    writeResult, err := svc.DefraSink.SendSync(ctx, defra.WriteOp{
        Collection: "OcrResult",
        Document:   ocrDoc,
        Op:         defra.OpCreate,
    })

    // Record metric (fire-and-forget)
    svc.DefraSink.Send(defra.WriteOp{
        Collection: "Metric",
        Document:   metric,
        Op:         defra.OpCreate,
    })

    return nil, nil
}
```

### Worker Processing

Workers also get enriched context:

```go
func (w *Worker) process(ctx context.Context, unit *WorkUnit) WorkResult {
    // Context already enriched by scheduler
    svc := ServicesFrom(ctx)

    // Worker can access registry, sink, etc if needed
    // ...
}
```

## Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         Server                               │
│  ┌─────────┐                                                │
│  │Services │ ─────────────────────────────────────────┐     │
│  └─────────┘                                          │     │
│       │                                               │     │
│       ▼                                               ▼     │
│  ┌─────────────┐     ┌───────────┐     ┌───────────────┐   │
│  │  HTTP Mux   │     │ Scheduler │     │    Workers    │   │
│  │ (middleware)│     │           │     │               │   │
│  └──────┬──────┘     └─────┬─────┘     └───────────────┘   │
│         │                  │                               │
│         ▼                  ▼                               │
│  ctx = WithServices   ctx = WithServices                   │
│         │                  │                               │
│         ▼                  ▼                               │
│  ┌──────────────┐    ┌──────────┐                          │
│  │   Handlers   │    │   Jobs   │                          │
│  │              │    │          │                          │
│  │ ServicesFrom │    │ Services │                          │
│  │   (ctx)      │    │ From(ctx)│                          │
│  └──────────────┘    └──────────┘                          │
└─────────────────────────────────────────────────────────────┘
```

## Initialization

Server creates Services once at startup:

```go
func (s *Server) Start(ctx context.Context) error {
    // ... start DefraDB, create client ...

    s.services = &Services{
        DefraClient: s.defraClient,
        DefraSink:   defra.NewSink(...),  // #123
        JobManager:  jobs.NewManager(s.defraClient, s.logger),
        Registry:    s.registry,
        Logger:      s.logger,
    }

    // Create scheduler with services reference
    s.scheduler = jobs.NewScheduler(jobs.SchedulerConfig{
        Manager:  s.services.JobManager,
        Services: s.services,  // Scheduler holds reference for context enrichment
        Logger:   s.logger,
    })
    s.services.Scheduler = s.scheduler

    // ...
}
```

## Benefits

1. **Uniform access** - Same pattern everywhere (handlers, jobs, workers)
2. **Easy to extend** - Add new service to struct, available everywhere
3. **Testable** - Build test context with mock services
4. **Aligns with sink pattern** - #123 already uses `SinkFromContext`
5. **No constructor churn** - Adding dependencies doesn't change signatures

## Testing

```go
func TestOcrJob(t *testing.T) {
    mockSink := defra.NewMockSink()
    mockManager := jobs.NewMockManager()

    ctx := WithServices(context.Background(), &Services{
        DefraSink:  mockSink,
        JobManager: mockManager,
    })

    job := NewOcrJob(...)
    units, err := job.Start(ctx)

    // Assert on mock interactions
}
```

## Migration

1. Add `Services` struct and context helpers to `internal/server/`
2. Update `Server` to create and hold `Services`
3. Add middleware to enrich HTTP request contexts
4. Update `Scheduler` to accept and propagate services
5. Refactor handlers to use `ServicesFrom(ctx)` instead of `s.jobManager`
6. Refactor jobs to use `ServicesFrom(ctx)`

## Relationship to Other ADRs

- **006 (Worker Architecture)** - Jobs/workers receive services via context
- **#123 (DefraDB Sink)** - Sink accessed via `ServicesFrom(ctx).DefraSink`
- **#121 (CLI/Server Routes)** - Endpoints use context pattern for handlers

## Decisions

1. **Location: `internal/svcctx/`** - Services lives in a separate package to avoid import cycles between server and endpoints. The server creates the Services struct and injects it into context; endpoints extract services via the svcctx package.

2. **Individual extractors** - Provide specific extractors for common access patterns:
   ```go
   // internal/svcctx/svcctx.go
   func ServicesFrom(ctx context.Context) *Services
   func DefraClientFrom(ctx context.Context) *defra.Client
   func DefraSinkFrom(ctx context.Context) *defra.Sink
   func JobManagerFrom(ctx context.Context) *jobs.Manager
   func RegistryFrom(ctx context.Context) *providers.Registry
   func SchedulerFrom(ctx context.Context) *jobs.Scheduler
   func LoggerFrom(ctx context.Context) *slog.Logger
   ```
   This keeps call sites clean - `svcctx.JobManagerFrom(ctx)` vs `svcctx.ServicesFrom(ctx).JobManager`.
