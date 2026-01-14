# process_book Architecture

## Table of Contents
- [Pipeline Overview](#pipeline-overview)
- [Job Structure](#job-structure)
- [State Management](#state-management)
- [Work Unit Lifecycle](#work-unit-lifecycle)
- [Concurrency Model](#concurrency-model)
- [Key Files](#key-files)

## Pipeline Overview

```
Page-Level Operations (Parallel)          Book-Level Operations (Sequential)
─────────────────────────────             ───────────────────────────────────

Page 1 ─→ Extract ─→ OCR (multi-provider) ─→ Blend ──┐
Page 2 ─→ Extract ─→ OCR (multi-provider) ─→ Blend ──┼─→ Label ──┐
  ...                                                │           │
Page N ─→ Extract ─→ OCR (multi-provider) ─→ Blend ──┘           │
                                                                  │
                              ┌───────────────────────────────────┘
                              ↓
              Metadata (20+ blended pages)
              ToC Finder (30 consecutive blended pages)
              ToC Extraction (if ToC found)
              Pattern Analysis (ALL pages blended)
              ToC Entry Linking (all pages labeled + pattern done)
              Finalize ToC (inline sub-job)
              Common Structure (inline sub-job)
```

### Stage Dependencies

| Stage | Trigger Condition | Preconditions |
|-------|-------------------|---------------|
| Extract | Job Start() | PDF on disk |
| OCR | After extract | Image on disk |
| Blend | All OCR providers done for page | OCR results |
| Label | Blend done + Pattern Analysis done | Blended text |
| Metadata | 20+ pages blended | Blended text |
| ToC Finder | 30 consecutive blended from page 1 | Front matter pages |
| ToC Extract | ToC found | ToC page range |
| Pattern Analysis | ALL pages blended | All blended text |
| Link ToC | Pattern + Labels + ToC entries | All data ready |
| Finalize | Link ToC done | Linked entries |
| Structure | Finalize done | Validated ToC |

## Job Structure

```go
// internal/jobs/process_book/job/job.go
type Job struct {
    common.TrackedBaseJob[WorkUnitInfo]  // Generic tracker

    Book     *common.BookState  // In-memory state
    TocDocID string             // ToC record ID

    // Stateful agents
    TocAgent      *agent.Agent  // ToC finder agent
    LinkTocAgents map[int]*agent.Agent  // Per-entry linker agents

    // Embedded sub-jobs
    FinalizeJob  *finalize_toc_job.Job
    StructureJob *common_structure_job.Job

    Config Config
}
```

### TrackedBaseJob Pattern

All jobs embed `TrackedBaseJob[T]` for work unit tracking:

```go
// Register work unit with custom info
j.RegisterWorkUnit(unitID, WorkUnitInfo{
    UnitType: WorkUnitTypeOCR,
    PageNum:  pageNum,
    Provider: "openrouter",
})

// Look up in OnComplete
info, ok := j.GetWorkUnit(result.WorkUnitID)

// Clean up when done
j.RemoveWorkUnit(result.WorkUnitID)
```

## State Management

### Three-Tier Persistence

1. **In-Memory (BookState/PageState)** - Fast, immediate access
2. **Async DefraDB (sink.Send)** - Batched, non-blocking writes
3. **Sync DefraDB (sink.SendSync)** - Blocking, for critical operations

```go
// Write-through pattern
state.SetBlendResultWithHeadings(text, headings)  // 1. In-memory first
sink.Send(defra.WriteOp{...})                     // 2. Async to DB

// Critical creates use sync
result, _ := sink.SendSync(ctx, defra.WriteOp{   // Blocking
    Op: defra.OpCreate,
    Collection: "ToC",
    Document: {...},
})
j.TocDocID = result.DocID  // Need ID immediately
```

### BookState Key Fields

```go
type BookState struct {
    BookID    string
    PageCount int
    Pages     map[int]*PageState  // All page states

    // Operation states
    Metadata      *OperationState
    TocFinder     *OperationState
    TocExtract    *OperationState
    PatternAnalysis *OperationState
    LinkToc       *OperationState

    // Results
    TocEntries          []TocEntry
    PatternAnalysisResult *PatternResult

    // Config
    DebugAgents bool
}
```

### PageState Key Fields

```go
type PageState struct {
    PageNum       int
    DocID         string  // DefraDB doc ID

    // Stage completion
    ExtractDone   bool
    OcrComplete   bool
    BlendComplete bool
    LabelComplete bool

    // Results
    OcrResults     map[string]string  // provider -> text
    BlendMarkdown  string
    Headings       []string
    PageNumberLabel string
    RunningHeader   string
    IsTocPage       bool
}
```

### OperationState Pattern

```go
state := &OperationState{}

state.CanStart()   // true if OpNotStarted
state.Start()      // NotStarted → InProgress
state.Complete()   // InProgress → Complete
state.Fail(max)    // Increment retry, maybe → Failed
state.IsStarted()  // InProgress or Complete
state.IsDone()     // Complete or permanently Failed
state.Reset()      // Back to NotStarted (for retry)
```

## Work Unit Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│ 1. CreateXWorkUnit()                                        │
│    ├─ Build work unit with common helper                    │
│    ├─ RegisterWorkUnit(id, info)                            │
│    └─ Return *jobs.WorkUnit                                 │
├─────────────────────────────────────────────────────────────┤
│ 2. Worker executes (outside job)                            │
│    └─ Returns jobs.WorkResult                               │
├─────────────────────────────────────────────────────────────┤
│ 3. OnComplete(result)                                       │
│    ├─ GetWorkUnit(id) → info                                │
│    ├─ Switch on info.UnitType                               │
│    ├─ HandleXComplete() for specific logic                  │
│    ├─ Persist state changes                                 │
│    ├─ RemoveWorkUnit(id)                                    │
│    └─ Return new work units (if any)                        │
├─────────────────────────────────────────────────────────────┤
│ 4. On Failure                                               │
│    ├─ Check retry count < max                               │
│    ├─ createRetryUnit() if can retry                        │
│    └─ Mark permanently failed if exhausted                  │
└─────────────────────────────────────────────────────────────┘
```

## Concurrency Model

### Mutex Protection

```go
func (j *Job) Start(ctx context.Context) ([]jobs.WorkUnit, error) {
    j.Mu.Lock()
    defer j.Mu.Unlock()
    // All state mutations here
}

func (j *Job) OnComplete(ctx context.Context, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
    j.Mu.Lock()
    defer j.Mu.Unlock()
    // All state mutations here
}
```

**Assumption:** Job scheduler never calls Start/OnComplete concurrently.

### Parallel Work Units

- Multiple pages processed simultaneously
- Multiple OCR providers per page simultaneously
- Multiple ToC entry linkers simultaneously
- Each work unit is independent

### Sequential Constraints

- Blend waits for all OCR providers for that page
- Label waits for blend AND pattern analysis
- Book ops have strict ordering (see pipeline diagram)

## Key Files

| File | Purpose |
|------|---------|
| `internal/jobs/process_book/process_book.go` | Package entry, NewJob(), factory |
| `internal/jobs/process_book/job/job.go` | Job struct, Start(), OnComplete() |
| `internal/jobs/process_book/job/types.go` | WorkUnitInfo, constants |
| `internal/jobs/process_book/job/state.go` | MaybeStartBookOperations(), triggers |
| `internal/jobs/process_book/job/blend.go` | Blend stage handler |
| `internal/jobs/process_book/job/label.go` | Label stage handler |
| `internal/jobs/process_book/job/ocr.go` | OCR stage handler |
| `internal/jobs/process_book/job/extract.go` | Extract stage handler |
| `internal/jobs/process_book/job/metadata.go` | Metadata extraction |
| `internal/jobs/process_book/job/toc_finder.go` | ToC finder agent |
| `internal/jobs/process_book/job/toc_extract.go` | ToC extraction |
| `internal/jobs/process_book/job/link_toc.go` | ToC linking agents |
| `internal/jobs/process_book/job/pattern_analysis.go` | Pattern analysis |
| `internal/jobs/common/state.go` | BookState, PageState |
| `internal/jobs/common/load.go` | LoadBook(), state loading |
| `internal/jobs/common/persist.go` | Persistence helpers |
