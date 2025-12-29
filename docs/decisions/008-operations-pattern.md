# 8. Operations Pattern (Replacing Stages)

**Date:** 2025-12-29

**Status:** Proposed

## Context

The current architecture has a `Stage` interface that implies a linear pipeline (stage 1 → stage 2 → stage 3). In practice:

1. There's only one "stage" (`page_processing`) that does 7 distinct operations
2. The name "stage" suggests sequence, but execution is really "jobs that process schemas"
3. We want flexibility to compose operations into different jobs (e.g., "rerun just ToC", "add OCR source")

The real mental model is: **schemas + jobs that mutate them + history in DB**

## Decision

Replace the `Stage` abstraction with an **Operations** pattern:

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Jobs (user-facing, trigger-able)                   │
│ - process-pages, build-structure, rerun-toc, add-ocr-source │
│ - Compose Operations to achieve their goal                  │
│ - Implement jobs.Job interface (Start, OnComplete, Done)    │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Operations (reusable, composable)                  │
│ - OcrOp, BlendOp, LabelOp, TocFindOp, MetadataOp, etc.      │
│ - Know which schemas they mutate                            │
│ - Create WorkUnits for provider-bound work                  │
│ - Higher-level than WorkUnits, lower than Jobs              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: WorkUnits + Pools (provider dispatch)              │
│ - Rate limiting per provider                                │
│ - Queue management, retries                                 │
│ - Unchanged from current implementation                     │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: Schemas + History (DefraDB)                        │
│ - Book, Page, ToC, TocEntry, OcrResult, Metric              │
│ - Flags for progress (ocr_complete, blend_complete, etc.)   │
│ - Commits for provenance/audit                              │
└─────────────────────────────────────────────────────────────┘
```

## Operations Interface

```go
// Operation is a reusable unit of work that mutates schemas.
// Operations are composed by Jobs to achieve higher-level goals.
type Operation interface {
    // Name identifies this operation (e.g., "ocr", "blend", "label")
    Name() string

    // TargetSchemas returns which DefraDB collections this op mutates
    TargetSchemas() []string

    // CreateWorkUnits generates work units for items that need processing.
    // Takes context for DefraDB access and job state.
    CreateWorkUnits(ctx context.Context, state *JobState) ([]jobs.WorkUnit, error)

    // HandleResult processes a completed work unit and updates schemas.
    // Returns any follow-up work units (e.g., blend after OCR completes).
    HandleResult(ctx context.Context, state *JobState, result jobs.WorkResult) ([]jobs.WorkUnit, error)

    // IsComplete returns true when this operation has no more work for the given state.
    IsComplete(state *JobState) bool
}
```

## Example Jobs

### process-pages (existing, refactored)
```go
type ProcessPagesJob struct {
    bookID string
    ops    []Operation // [ExtractOp, OcrOp, BlendOp, LabelOp, MetadataOp, TocFindOp, TocExtractOp]
    state  *JobState
}
```

### rerun-toc (new, focused)
```go
type RerunTocJob struct {
    bookID string
    ops    []Operation // [TocFindOp, TocExtractOp] only
    state  *JobState
}
```

### add-ocr-source (new, focused)
```go
type AddOcrSourceJob struct {
    bookID   string
    provider string      // e.g., "google-vision"
    ops      []Operation // [OcrOp] with specific provider
    state    *JobState
}
```

### build-structure (future)
```go
type BuildStructureJob struct {
    bookID string
    ops    []Operation // [TocParseOp, ParagraphOp, ...]
    state  *JobState
}
```

## Migration Plan

### Phase 1: Extract Operations from page_processing
1. Create `internal/ops/` directory
2. Extract each operation from `internal/pipeline/stages/page_processing/job/`:
   - `extract.go` → `internal/ops/extract/`
   - `ocr.go` → `internal/ops/ocr/`
   - `blend.go` → `internal/ops/blend/`
   - `label.go` → `internal/ops/label/`
   - `metadata.go` → `internal/ops/metadata/`
   - `toc_finder.go` → `internal/ops/toc_find/`
   - `toc_extract.go` → `internal/ops/toc_extract/`
3. Each op implements the Operation interface
4. Keep prompts in `internal/ops/<op>/prompt.go`

### Phase 2: Refactor ProcessPagesJob
1. Move to `internal/jobs/process_pages/`
2. Compose operations instead of inline logic
3. JobState becomes shared across operations

### Phase 3: Delete Stage abstraction
1. Remove `internal/pipeline/stage.go`
2. Remove `internal/pipeline/registry.go`
3. Remove `internal/pipeline/stages/` (now in internal/ops/)
4. Update CLAUDE.md

### Phase 4: Add new focused jobs
1. `internal/jobs/rerun_toc/` - compose TocFindOp + TocExtractOp
2. `internal/jobs/add_ocr/` - compose OcrOp with provider param
3. Register with scheduler

## Directory Structure (After)

```
internal/
├── ops/                    # Operations (reusable building blocks)
│   ├── operation.go        # Operation interface
│   ├── extract/
│   │   └── extract.go
│   ├── ocr/
│   │   ├── ocr.go
│   │   └── workunit.go
│   ├── blend/
│   │   ├── blend.go
│   │   ├── prompt.go
│   │   └── schema.go
│   ├── label/
│   │   ├── label.go
│   │   ├── prompt.go
│   │   └── schema.go
│   ├── metadata/
│   │   ├── metadata.go
│   │   ├── prompt.go
│   │   └── schema.go
│   ├── toc_find/
│   │   ├── toc_find.go
│   │   ├── prompt.go
│   │   └── tools/
│   └── toc_extract/
│       ├── toc_extract.go
│       ├── prompt.go
│       └── schema.go
├── jobs/                   # Jobs (user-facing, composable)
│   ├── job.go              # Job interface (unchanged)
│   ├── scheduler.go        # (unchanged)
│   ├── process_pages/      # Big composite job
│   │   ├── job.go
│   │   └── state.go
│   ├── rerun_toc/          # Focused job
│   │   └── job.go
│   └── add_ocr/            # Focused job
│       └── job.go
├── schema/                 # DefraDB schemas (unchanged)
└── defra/                  # DefraDB client (unchanged)
```

## What Gets Deleted

- `internal/pipeline/stage.go` - Stage interface
- `internal/pipeline/registry.go` - Stage registry
- `internal/pipeline/stages/` - Stages directory (content moves to ops/)

## Benefits

1. **Composability** - Mix operations to create new jobs easily
2. **Clarity** - "Operation" is what it does; "Job" is user-triggered
3. **Flexibility** - Re-run specific operations, add new providers
4. **Testability** - Test operations in isolation
5. **No false sequence** - Jobs define order, not a "pipeline"

## Open Questions

1. Should JobState be shared or per-operation?
2. How do operations declare dependencies on each other?
3. Should we have an OperationRegistry or just construct in job code?
