# 5. DefraDB as Source of Truth

**Date:** 2025-12-15

**Status:** Accepted

## Decision

**All state lives in DefraDB. Not files. Every change is verifiable.**

DefraDB provides cryptographically verifiable data provenance via Merkle CRDTs.

## Why DefraDB

| Feature | Benefit for Shelf |
|---------|-------------------|
| **Merkle DAG** | Every change has a CID (content identifier) |
| **Full History** | Query any document's complete change history |
| **Cryptographic Proofs** | Verify data integrity, trace issues to source |
| **CRDT Conflict Resolution** | Multi-writer safety for parallel processing |
| **GraphQL API** | Query progress, filter by status |

## Data Provenance

Every document change creates an immutable block:
- **CID** (SHA256 content hash) - unique identifier
- **Parent links** - chain of previous states
- **Optional signatures** - ED25519/ECDSA authorship proof

```graphql
# Query full history of a page
query {
  _commits(docID: "page-123") {
    cid
    height
    links { cid }
  }
}
```

## Issue Tracing

When OCR output is wrong, trace back:
1. Query page's commit history
2. Find which stage wrote the bad data
3. See exact input that produced the output
4. Identify the provider/model that failed

No more "where did this come from?"

## Implementation

```go
// Check progress
result := client.ExecRequest(ctx, `{
  pages(filter: {ocrComplete: true}) { _docID }
}`)

// Record completion (creates verifiable commit)
col.Update(ctx, doc)

// Query history when debugging
history := client.ExecRequest(ctx, `{
  _commits(docID: "...") { cid height }
}`)
```

## What This Replaces

Python used filesystem as database. Files existed = work done. No history, no verification.

Go uses DefraDB. Full audit trail. Cryptographic proof of every change.

## Write Sink

All writes flow through a single coordinated sink. Not scattered client calls.

| Mode | Use Case |
|------|----------|
| **Send** | Fire-and-forget. Metrics, logs. Don't block. |
| **SendSync** | Need the docID back. Stage outputs, job records. |

Batching happens automatically:
- Size trigger (100 ops)
- Time trigger (5s)
- Manual flush when needed

```go
// Fire-and-forget (metrics)
sink.Send(defra.WriteOp{
    Collection: "Metric",
    Document:   map[string]any{"cost": 0.002},
    Op:         defra.OpCreate,
})

// Blocking (need docID)
result, _ := sink.SendSync(ctx, defra.WriteOp{
    Collection: "OcrResult",
    Document:   ocrDoc,
    Op:         defra.OpCreate,
})
// result.DocID available immediately
```

Access via context: `svcctx.DefraSinkFrom(ctx)`.

## Schema Versioning

DefraDB tracks schema changes too:
- Collections have immutable `VersionID`
- Schema migrations form a DAG
- Can evolve stage schemas without losing history
