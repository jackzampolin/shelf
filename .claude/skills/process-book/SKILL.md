---
name: process-book
description: Guide for working with the process_book job in the shelf book digitization pipeline. Use when modifying, debugging, or understanding the job orchestration patterns, work unit lifecycle, state management, or when adding new pipeline stages. Specific stages may change over time; this skill focuses on durable patterns.
---

# Working with process_book

The `process_book` job orchestrates the book digitization pipeline using a work unit pattern. Specific stages may change, but the underlying patterns are stable.

## Quick Reference

| Task | Reference |
|------|-----------|
| Understand pipeline architecture | [architecture.md](references/architecture.md) |
| Stage implementation patterns | [stages.md](references/stages.md) |
| Debug issues | [debugging.md](references/debugging.md) |
| Add/modify stages | [adding-stages.md](references/adding-stages.md) |

## Key Locations

```
internal/jobs/process_book/
├── process_book.go       # Package entry, NewJob(), factory
└── job/
    ├── job.go            # Job struct, Start(), OnComplete()
    ├── types.go          # WorkUnitInfo, constants
    ├── state.go          # MaybeStartBookOperations(), triggers
    └── [stage].go        # One file per stage

internal/jobs/common/
├── state.go              # BookState, PageState, OperationState
├── load.go               # LoadBook()
├── persist.go            # Persistence helpers
└── [stage].go            # Shared stage logic
```

## Core Patterns

### Work Unit Lifecycle

```go
// 1. Create and register
unit := j.CreateXWorkUnit(ctx, pageNum, state)
j.RegisterWorkUnit(unit.ID, WorkUnitInfo{...})

// 2. Worker executes (external)

// 3. Handle completion
func (j *Job) OnComplete(ctx, result) {
    info, _ := j.GetWorkUnit(result.WorkUnitID)
    switch info.UnitType {
    case WorkUnitTypeX:
        return j.HandleXComplete(ctx, info, result)
    }
}

// 4. Clean up
j.RemoveWorkUnit(result.WorkUnitID)
```

### State Persistence

```go
// Write-through (in-memory first, then async to DB)
state.SetComplete(true)                // Immediate
sink.Send(defra.WriteOp{...})          // Async

// Sync for critical operations (record creation, relationships)
result, _ := sink.SendSync(ctx, op)    // Blocking
```

### Cascading Triggers (state.go)

```go
func (j *Job) MaybeStartBookOperations(ctx) []jobs.WorkUnit {
    if j.SomeThreshold() && j.Book.SomeOp.CanStart() {
        j.Book.SomeOp.Start()
        return []jobs.WorkUnit{j.CreateSomeWorkUnit(ctx)}
    }
    // ... more triggers
}
```

### OperationState API

```go
op.CanStart()   // true if not started
op.Start()      // NotStarted → InProgress
op.Complete()   // InProgress → Complete
op.Fail(max)    // Increment retry, maybe → Failed
op.IsDone()     // Complete or permanently Failed
```

## Stage Categories

| Category | Pattern | State | Example |
|----------|---------|-------|---------|
| Page-level | Per-page parallel | PageState | OCR, blend |
| Book-level | Threshold trigger | OperationState | Metadata |
| Agent-based | Multi-turn loop | Agent struct | ToC finder |
| Multi-phase | Parallel → sequential | Partitioned | Analysis |
| Sub-job | Embedded job | Sub-job state | Finalize |

See [stages.md](references/stages.md) for implementation patterns.

## Debugging

### Via API
```bash
shelf api jobs status <book-id>      # Stage progress
shelf api books get <book-id>        # Book state
shelf api agent-logs list --job-id X # Agent logs (if debug enabled)
```

### Via DefraDB
```graphql
{ Page(filter: {book_id: {_eq: "<id>"}}) { page_num blend_complete label_complete } }
{ Book(filter: {_docID: {_eq: "<id>"}}) { metadata_complete pattern_analysis_complete } }
```

See [debugging.md](references/debugging.md) for full query reference.

## Common Tasks

### Add a new stage
1. Define `WorkUnitTypeX` constant in types.go
2. Add state fields to PageState or BookState
3. Create handler file with `CreateX` and `HandleXComplete`
4. Add case to `OnComplete()` switch
5. Add trigger in handler or `MaybeStartBookOperations()`
6. Add persistence helper in common/persist.go

See [adding-stages.md](references/adding-stages.md) for full guide.

### Debug a stuck stage
1. Query DB for precondition states
2. Check `*_started` / `*_complete` flags
3. Enable debug: `Config.DebugAgents = true`
4. Check agent logs if agent-based

### Trace work unit flow
```go
logger.Debug("work unit", "type", info.UnitType, "page", info.PageNum, "success", result.Success)
```
