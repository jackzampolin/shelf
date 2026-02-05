# ADR 009: BookState Repository Pattern

## Status

Accepted

## Context

The book processing pipeline requires reading and writing per-book data (chapters, ToC entries, pages, OCR results, agent states) to DefraDB. Previously, this was done through various patterns:

1. Direct `defraClient` calls scattered throughout job code
2. `sink.Send` / `sink.SendSync` calls for fire-and-forget writes
3. Free functions in `persist.go` that extract client/sink from context

This created several problems:

- **Inconsistent patterns**: Some code used direct client calls, others used sink, others used persist helpers
- **Untestable**: Code that used `svcctx.DefraClientFrom(ctx)` was hard to unit test without a live DefraDB
- **Memory/DB divergence**: Easy to update DB without updating in-memory state, or vice versa
- **No single source of truth**: Per-book data access was spread across many files

## Decision

Make `BookState` the sole repository for all per-book DefraDB reads and writes. The key principles are:

### 1. BookState Owns Per-Book Data

All per-book data (chapters, ToC entries, pages, OCR results, agent states, book fields) flows through BookState methods. No per-book code touches `defraClient` or `sink` directly.

### 2. StateStore Interface for Abstraction

The `StateStore` interface abstracts DB operations:

```go
type StateStore interface {
    Execute(ctx context.Context, query string, variables map[string]any) (*defra.GQLResponse, error)
    Send(op defra.WriteOp)
    SendSync(ctx context.Context, op defra.WriteOp) (defra.WriteResult, error)
    SendManySync(ctx context.Context, ops []defra.WriteOp) ([]defra.WriteResult, error)
    UpsertWithVersion(ctx context.Context, collection string, filter, createInput, updateInput map[string]any) (defra.WriteResult, error)
    UpdateWithVersion(ctx context.Context, collection string, docID string, input map[string]any) (defra.WriteResult, error)
}
```

- **DefraStateStore**: Production implementation delegating to DefraDB client and sink
- **MemoryStateStore**: In-memory implementation for unit testing

### 3. Write-Through Pattern

Every persist method atomically updates both DB and memory:

```go
func (b *BookState) PersistBookStatus(ctx context.Context, status string) (string, error) {
    store := b.getStore(ctx)
    result, err := store.SendSync(ctx, defra.WriteOp{...})
    if err != nil {
        return "", err
    }

    b.mu.Lock()
    b.trackCIDLocked("Book", b.BookID, result.CID)
    b.bookCID = result.CID
    b.mu.Unlock()

    return result.CID, nil
}
```

### 4. Domain-Organized Persist Methods

Persist methods are organized by domain in separate files:

- `state_persist_book.go` — Book field operations (status, metadata, operation state, progress)
- `state_persist_chapters.go` — Chapter operations (skeleton, extract, classify, polish)
- `state_persist_toc.go` — ToC entry operations (create, link, resort, delete)
- `state_persist_pages.go` — Page/OCR operations (ocr result, markdown, reset)
- `state_persist_agents.go` — Agent state operations (create, delete by type/all)

### 5. Bounded Concurrency for Batches

Batch operations use bounded concurrent goroutines internally:

```go
const maxConcurrentChapterWrites = 5

func (b *BookState) PersistChapterSkeleton(ctx context.Context, ...) error {
    sem := make(chan struct{}, maxConcurrentChapterWrites)
    // ... concurrent goroutines acquire semaphore before DB write
}
```

Callers don't need to manage concurrency — it's handled internally.

### 6. Backward Compatibility During Migration

BookState persist methods check `b.Store != nil` before using it. If nil, they fall back to extracting sink/client from context:

```go
func (b *BookState) getStore(ctx context.Context) StateStore {
    if b.Store != nil {
        return b.Store
    }
    client := svcctx.DefraClientFrom(ctx)
    sink := svcctx.DefraSinkFrom(ctx)
    if client != nil && sink != nil {
        return &DefraStateStore{Client: client, Sink: sink}
    }
    return nil
}
```

This allows gradual migration without breaking existing code paths.

## Scope

**In scope**: All per-book data:
- Book fields (status, metadata, operation state, progress counters)
- Chapters (skeleton, extract results, classifications, polish results)
- ToC entries (create, link to pages, resort, delete)
- Pages (OCR results, markdown, headings)
- Agent states (create, update, delete)

**Out of scope**: Non-book data continues using existing patterns:
- Prompts (`prompts/store.go`)
- Voices (`endpoints/voices.go`)
- LLM call recording (`llmcall/recorder.go`)
- Agent observability logging (`agent/observability/logger.go`)

## Consequences

### Positive

- **Testability**: Unit tests can use MemoryStateStore without DefraDB
- **Consistency**: Single place for all per-book data access
- **Atomicity**: Memory and DB always updated together
- **CID tracking**: All writes automatically tracked for provenance
- **Thread safety**: All methods properly synchronized

### Negative

- **Migration effort**: Existing code must be migrated to use BookState methods
- **Learning curve**: Developers must learn the new patterns
- **Method proliferation**: BookState gains many persist methods

### Migration Path

Migration proceeds in phases:

1. **Phase 1**: Expand StateStore interface with new methods
2. **Phase 2**: Add BookState persist methods
3. **Phase 3**: Migrate callers one domain at a time
4. **Phase 4**: Remove deprecated free functions and direct DB access

## References

- ADR 005: DefraDB Source of Truth
- ADR 007: Services Context
- `internal/jobs/common/state_store.go` — StateStore interface
- `internal/jobs/common/state_persist_*.go` — Persist method implementations
