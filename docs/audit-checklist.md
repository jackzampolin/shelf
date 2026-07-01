# Codebase Audit Checklist

Reference document for auditing the shelf-go codebase against architectural decisions.

## When to Audit

After a feature stabilizes:
1. Spike on feature, push to working
2. Cleanup during implementation
3. **Audit** (this checklist)

## Quick Reference: ADRs

| ADR | Name | Key Check |
|-----|------|-----------|
| 000 | Information Hygiene | Context clarity, small focused files |
| 001 | Cordon Sanitaire | No TODO comments, ideas in GitHub |
| 002 | Cost Tracking | Metrics on every LLM/OCR call |
| 003 | File Organization | One concept per file, <400 lines |
| 004 | Naming Conventions | Consistent hyphen-case, PascalCase |
| 005 | DefraDB Source of Truth | All state in DB, not files |
| 006 | Worker Architecture | Jobs for all work, rate limiting |
| 007 | Services Context | svcctx extractors, not constructors |
| 008 | Config and Prompts in Database | Config/prompts stored in DefraDB |
| 009 | BookState Repository | BookState is sole per-book DB access path |
| 010 | Async Writes Refactor | Per-book DB writes are fire-and-forget |
| 011 | Local Inference Zero Cost | Local providers report CostUSD: 0 |

---

## Pass 1: Top-Down Architecture

**Goal:** Verify high-level structure is clean.

### Entry Points (`cmd/shelf/`)
- [ ] `main.go` - Just calls root command
- [ ] `root.go` - Cobra setup, no business logic
- [ ] `serve.go` - Server wiring only
- [ ] `api.go` - CLI commands delegate to client

**Red flags:**
- Business logic in cmd/
- Direct DefraDB calls from CLI
- Hardcoded values that should be config

### Package Dependencies
- [ ] No import cycles
- [ ] Dependency direction: `cmd → internal/server → internal/* → external`
- [ ] Lower packages don't know about higher packages

**Check with:**
```bash
go mod graph | grep shelf
```

---

## Pass 2: Bottom-Up Implementation

**Goal:** Every file follows ADRs.

### File Size (ADR 003)
```bash
find internal/ -name "*.go" ! -name "*_test.go" -exec wc -l {} + | sort -rn
```

| Lines | Status |
|-------|--------|
| <200 | Good |
| 200-400 | Review |
| >400 | Split required |

### One Concept Per File (ADR 003)
Each file should have ONE of:
- One type + its methods
- One interface + implementations
- One set of related functions

**Red flags:**
- `utils.go`, `helpers.go`, `misc.go`
- Multiple unrelated types
- God files

### Naming (ADR 004)

| Thing | Convention | Example |
|-------|------------|---------|
| Packages | lowercase | `jobs`, `providers` |
| Files | snake_case | `rate_limiter.go` |
| Exports | PascalCase | `type Worker struct` |
| Unexported | camelCase | `func processUnit()` |
| Stages | hyphen-case | `ocr-pages`, `label-structure` |
| ADRs | NNN-kebab-case | `007-services-context.md` |

### No TODO Comments (ADR 001)
```bash
grep -rn "TODO\|FIXME\|XXX\|HACK" internal/ --include="*.go"
```
Should return nothing. Ideas go in GitHub issues.

---

## Pass 3: Context/Services Usage (ADR 007)

**Goal:** Services flow through context, not constructors.

### HTTP Handlers
```go
// CORRECT
func (e *Endpoint) handler(w http.ResponseWriter, r *http.Request) {
    jm := svcctx.JobManagerFrom(r.Context())
    // ...
}

// WRONG
func (e *Endpoint) handler(w http.ResponseWriter, r *http.Request) {
    jobs := e.jobManager.List(...)  // struct field access
}
```

### Jobs
```go
// CORRECT
func (j *MyJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
    sink := svcctx.DefraSinkFrom(ctx)
    // ...
}

// WRONG
func (j *MyJob) OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error) {
    j.sink.Send(...)  // struct field from constructor
}
```

### Available Extractors
```go
svcctx.ServicesFrom(ctx)      // Full services struct
svcctx.DefraClientFrom(ctx)   // *defra.Client
svcctx.DefraSinkFrom(ctx)     // *defra.Sink
svcctx.JobManagerFrom(ctx)    // *jobs.Manager
svcctx.RegistryFrom(ctx)      // *providers.Registry
svcctx.SchedulerFrom(ctx)     // *jobs.Scheduler
svcctx.LoggerFrom(ctx)        // *slog.Logger
```

### Check for violations
```bash
# Look for constructor patterns that should use context
grep -rn "func New.*Manager\|func New.*Client" internal/ --include="*.go"
```

---

## Pass 4: DefraDB/Storage (ADR 005)

**Goal:** All state in DefraDB, not filesystem.

### No Filesystem State
```bash
# Should return nothing (except legitimate file ops)
grep -rn "os.WriteFile\|os.Create\|ioutil.WriteFile" internal/ --include="*.go"
```

Legitimate exceptions:
- Writing to `~/.shelf/` config
- Temporary files during processing
- Test fixtures

### DefraSink Usage

| Method | Use Case | Blocks? |
|--------|----------|---------|
| `Send()` | Metrics, logs | No |
| `SendSync()` | Need docID back | Yes |

```go
// Fire-and-forget (metrics)
sink.Send(defra.WriteOp{
    Collection: "Metric",
    Document:   metric,
    Op:         defra.OpCreate,
})

// Need the ID
result, _ := sink.SendSync(ctx, defra.WriteOp{
    Collection: "Page",
    Document:   page,
    Op:         defra.OpCreate,
})
pageID := result.DocID
```

### Query Patterns
```go
// Good: GraphQL query
result := client.ExecRequest(ctx, `{
    pages(filter: {bookId: {_eq: "..."}}) {
        _docID
        pageNumber
    }
}`)

// Bad: filesystem scan
files, _ := os.ReadDir(bookPath)
```

---

## Pass 5: Job/Worker Patterns (ADR 006)

**Goal:** All work through job system, properly tracked.

### Job Interface Compliance
```go
type Job interface {
    ID() string
    SetRecordID(id string)
    Type() string
    Start(ctx context.Context) ([]WorkUnit, error)
    OnComplete(ctx context.Context, result WorkResult) ([]WorkUnit, error)
    Done() bool
    Status(ctx context.Context) (map[string]string, error)
}
```

Check each job implementation has all methods.

### Worker Rate Limiting
```go
// Workers must use rate limiter
type Worker struct {
    rateLimiter *providers.RateLimiter
}

func (w *Worker) Process(ctx context.Context, unit *WorkUnit) WorkResult {
    w.rateLimiter.Wait(ctx)  // Must block for rate limit
    // ...
}
```

### Metrics Recording (ADR 002)
Every LLM/OCR call should record:
- Provider
- Model
- Input/output tokens
- Cost
- Latency
- Success/failure

```go
// After every API call
metrics.Record(ctx, MetricOpts{
    Provider: "openrouter",
    Model:    "gpt-4",
    Tokens:   response.Usage,
    Cost:     calculateCost(response),
})
```

---

## Pass 6: Package-by-Package

For each package in `internal/`:

### Quick Checks
- [ ] Purpose clear from name?
- [ ] Files focused (<400 lines)?
- [ ] Exports intentional?
- [ ] Tests exist?

### Packages

| Package | Purpose | Key Files |
|---------|---------|-----------|
| `agent/` | LLM agent with tools | `agent.go`, `tools.go` |
| `agents/` | Specialized agent factories | `*_factory.go`, `helpers.go` |
| `api/` | Endpoint interface | `endpoint.go`, `client.go` |
| `config/` | Config + hot-reload | `config.go`, `schema.go`, `store.go` |
| `defra/` | DefraDB client | `client.go`, `sink.go` |
| `epub/` | ePub 3.0 generation | `builder.go`, `package.go` |
| `home/` | ~/.shelf directory | `home.go` |
| `ingest/` | Book intake | `ingest.go`, `job.go`, `stitch.go` |
| `jobcfg/` | Job configuration | `builder.go` |
| `jobs/` | Job system + implementations | `job.go`, `manager.go`, `scheduler.go` |
| `llmcall/` | LLM call tracking | `call.go`, `store.go` |
| `metrics/` | Cost tracking | `metric.go`, `query.go` |
| `prompts/` | Prompt templates | `resolver.go`, `store.go`, `template.go` |
| `providers/` | LLM/OCR clients | `provider.go`, `registry.go`, `openrouter.go` |
| `schema/` | GraphQL schemas | `registry.go` |
| `server/` | HTTP server | `server.go` |
| `svcctx/` | Services context | `svcctx.go` |
| `testutil/` | Test helpers | `docker.go`, `env.go` |
| `types/` | Shared types (no internal deps) | `chapter.go` |
| `voices/` | TTS voice management | `sync.go` |

---

## Slash Commands

```bash
/audit-full      # Complete multi-pass audit
/audit-quick     # Fast check for common issues
/audit-package X # Deep dive on single package
```

---

## Post-Audit

After completing audit:
1. Commit fixes with type `refactor:` or `fix:`
2. Update ADRs if patterns evolved
3. Create GitHub issues for deferred work
4. Update CLAUDE.md if conventions changed
