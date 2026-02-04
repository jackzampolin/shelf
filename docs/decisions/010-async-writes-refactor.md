# ADR 010: Async-Only DB Writes for Per-Book Operations

## Status
Proposed

## Context

BookState serves as a write-through cache for all per-book data during job execution. We recently converted stage transitions to use async DB writes, reducing the toc_finder → extract_toc latency from **112 seconds to ~10 seconds** (92% improvement).

The current codebase still has many `SendSync` calls that block on DB writes, adding unnecessary latency. With BookState as the authoritative source during execution, we can eliminate all sync writes for per-book operations.

## Decision

**All per-book DB writes will be fire-and-forget.** BookState is the single source of truth during job execution. The database is used only for:
1. Crash recovery (reload state on restart)
2. External visibility (REST API when no active job)

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Job Execution                          │
│                                                             │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │  Scheduler  │───▶│  BookState  │◀───│  REST API   │     │
│  └─────────────┘    │  (memory)   │    └─────────────┘     │
│                     └──────┬──────┘                         │
│                            │ fire-and-forget                │
│                            ▼                                │
│                     ┌─────────────┐                         │
│                     │    Sink     │                         │
│                     │  (buffered) │                         │
│                     └──────┬──────┘                         │
│                            │ batched writes                 │
│                            ▼                                │
│                     ┌─────────────┐                         │
│                     │   DefraDB   │                         │
│                     └─────────────┘                         │
└─────────────────────────────────────────────────────────────┘
```

### Key Principles

1. **Memory-first**: All state changes update BookState immediately
2. **Fire-and-forget DB**: All DB writes use `sink.Send()` (non-blocking)
3. **No CID tracking during execution**: CIDs are for versioning/attribution, not required for job logic
4. **Upsert for creates**: Use upsert patterns to avoid needing DocID back synchronously
5. **REST API reads from BookState**: When job is active, API reads memory; when not, reads DB

## Implementation Plan

### Phase 1: Remove Sync from BookState Persist Methods

**Files:** `internal/jobs/common/state_persist_*.go`

Convert all sync methods to async-only. The sync versions become thin wrappers for backward compatibility during migration, then are removed.

| Current Method | Change |
|----------------|--------|
| `PersistBookStatus` | Convert to async, remove CID return |
| `PersistMetadataResult` | Convert to async |
| `PersistOpState` | Already has async version, remove sync |
| `PersistOpComplete` | Convert to async |
| `PersistStructurePhase` | Already has async version, remove sync |
| `PersistFinalizePhase` | Already has async version, remove sync |
| `PersistFinalizeProgress` | Convert to async |
| `PersistTocLinkProgress` | Convert to async |
| `PersistTocRecord` | Use upsert, fire-and-forget |
| `PersistTocFinderResult` | Already has async version, remove sync |
| `PersistTocEntries` | Convert to async batch |
| `PersistTocEntryLink` | Convert to async |
| `PersistChapterSkeleton` | Convert to async batch |
| `PersistChapterExtracts` | Convert to async batch |
| `PersistChapterClassifications` | Convert to async batch |
| `PersistChapterPolish` | Convert to async batch |
| `PersistOcrResult` | Convert to async |
| `PersistOcrMarkdown` | Convert to async |
| `PersistNewAgentState` | Convert to async |

### Phase 2: Remove Legacy Sync Functions

**Files:** `internal/jobs/common/toc.go`, `internal/jobs/common/persist.go`, `internal/jobs/common/metadata_ops.go`

Remove or convert:
- `SaveTocFinderResult` → Already replaced by `PersistTocFinderResultAsync`
- `SaveTocFinderNoResult` → Convert to async
- `SaveTocExtractResult` → Convert to async
- `SaveTocEntryResult` → Convert to async
- `SaveMetadataResult` → Convert to async
- `SendTracked` → Remove (replace callers with async methods)
- `SendManyTracked` → Remove (replace callers with async batch methods)

### Phase 3: Update All Callers

Search for remaining `SendSync` calls and convert:

```bash
grep -rn "SendSync\|\.SendSync" internal/jobs/ --include="*.go" | grep -v "_test.go"
```

Each caller should:
1. Update memory state first (already happens via BookState methods)
2. Call async persist method (fire-and-forget)
3. Continue immediately without waiting

### Phase 4: REST API BookState Access

**Files:** `internal/server/endpoints/books_*.go`, `internal/jobs/scheduler.go`

Add mechanism for REST API to read from active BookState:

```go
// In Scheduler
func (s *Scheduler) GetActiveBookState(bookID string) *common.BookState {
    s.mu.RLock()
    defer s.mu.RUnlock()

    for _, job := range s.jobs {
        if provider, ok := job.(BookIDProvider); ok {
            if provider.BookID() == bookID {
                if bookProvider, ok := job.(BookStateProvider); ok {
                    return bookProvider.BookState()
                }
            }
        }
    }
    return nil
}

// In REST endpoint
func (e *GetBookEndpoint) handler(w http.ResponseWriter, r *http.Request) {
    bookID := chi.URLParam(r, "id")
    scheduler := svcctx.SchedulerFrom(r.Context())

    // Try active BookState first
    if bookState := scheduler.GetActiveBookState(bookID); bookState != nil {
        // Return data from memory
        return respondWithBookState(w, bookState)
    }

    // Fall back to DB
    return respondFromDB(w, r.Context(), bookID)
}
```

### Phase 5: Simplify StateStore Interface

**Files:** `internal/jobs/common/state_store.go`

Once all per-book code uses async writes, simplify the interface:

```go
type StateStore interface {
    // Reads (still needed)
    Execute(ctx context.Context, query string, variables map[string]any) (*defra.GQLResponse, error)

    // Async writes (fire-and-forget)
    Send(op defra.WriteOp)
    SendMany(ops []defra.WriteOp)

    // Upsert (for creates where we need to track DocID in memory)
    Upsert(ctx context.Context, collection string, filter, create, update map[string]any) (docID string, err error)
}
```

Note: `SendSync` may be kept for edge cases (initial job record creation, non-book data) but removed from per-book hot paths.

### Phase 6: Cleanup and Documentation

1. Remove deprecated sync methods
2. Update CLAUDE.md with new patterns
3. Add inline documentation explaining write-through cache pattern
4. Update tests to verify async behavior

## Consequences

### Positive
- **Dramatically reduced latency** between pipeline stages (proven: 112s → 10s)
- **Simpler mental model**: Memory is truth, DB is backup
- **Better throughput**: No blocking on DB writes
- **Cleaner code**: Remove error handling for sync write failures in hot paths

### Negative
- **Eventual consistency**: Brief window where DB lags memory (acceptable)
- **No CID tracking**: Lose fine-grained version tracking during execution (acceptable for job logic)
- **Crash recovery complexity**: Must re-derive some state from DB on restart (already handled)

### Neutral
- **Testing**: MemoryStateStore already supports async (Send is synchronous in tests for determinism)

## Migration Path

1. Phase 1-2: Can be done incrementally, file by file
2. Phase 3: Search and replace, verify with tests
3. Phase 4: New feature, can be added independently
4. Phase 5-6: Cleanup after all callers migrated

## Verification

After each phase:
1. `go build ./...` - compiles
2. `make test` - all tests pass
3. E2E test - process a book, verify timing improvements
4. Verify no `SendSync` in hot paths: `grep -rn "SendSync" internal/jobs/`

## References

- ADR 009: BookState Repository Pattern
- Commit `1ae5ff2`: Initial async for toc_finder → toc_extract
- Commit `8eca510`: Async across all stage transitions
- E2E timing data: 112s → 10s latency reduction
