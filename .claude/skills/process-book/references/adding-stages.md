# Adding and Modifying Stages

## Table of Contents
- [Adding a New Stage](#adding-a-new-stage)
- [Modifying Existing Stages](#modifying-existing-stages)
- [Common Patterns](#common-patterns)

## Adding a New Stage

### Step 1: Define WorkUnitType

```go
// internal/jobs/process_book/job/types.go
const WorkUnitTypeNewStage = "new_stage"
```

### Step 2: Add WorkUnitInfo Fields

```go
// internal/jobs/process_book/job/types.go
type WorkUnitInfo struct {
    UnitType string
    PageNum  int
    // ... existing fields

    // Add fields for new stage tracking
    NewStageParam string
}
```

### Step 3: Add State (if needed)

**For page-level state:**
```go
// internal/jobs/common/state.go - PageState
type PageState struct {
    // ... existing
    NewStageComplete bool
    NewStageResult   string
}

func (s *PageState) IsNewStageDone() bool {
    s.mu.RLock()
    defer s.mu.RUnlock()
    return s.NewStageComplete
}

func (s *PageState) SetNewStageResult(result string) {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.NewStageComplete = true
    s.NewStageResult = result
}
```

**For book-level state:**
```go
// internal/jobs/common/state.go - BookState
type BookState struct {
    // ... existing
    NewStageOp *OperationState
}
```

### Step 4: Create Stage Handler File

```go
// internal/jobs/process_book/job/new_stage.go
package job

import (
    "context"

    "github.com/jackzampolin/shelf/internal/jobs"
    "github.com/jackzampolin/shelf/internal/jobs/common"
    "github.com/jackzampolin/shelf/internal/svcctx"
)

func (j *Job) CreateNewStageWorkUnit(ctx context.Context, pageNum int, state *common.PageState) *jobs.WorkUnit {
    // Build input for the work unit
    input := new_stage.Input{
        PageNum:      pageNum,
        BlendMarkdown: state.GetBlendMarkdown(),
        // ... other inputs
    }

    // Create work unit using common helper (or directly)
    unit := common.CreateNewStageWorkUnit(ctx, j, input)
    if unit == nil {
        return nil
    }

    // Register with tracker
    j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
        UnitType: WorkUnitTypeNewStage,
        PageNum:  pageNum,
    })

    return unit
}

func (j *Job) HandleNewStageComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
    logger := svcctx.LoggerFrom(ctx)

    state, ok := j.Book.Pages[info.PageNum]
    if !ok {
        return nil, fmt.Errorf("page %d not found", info.PageNum)
    }

    // Parse result
    if result.ChatResult == nil || result.ChatResult.ParsedJSON == nil {
        return nil, fmt.Errorf("missing result")
    }

    // Save result
    if err := common.SaveNewStageResult(ctx, state, result); err != nil {
        return nil, err
    }

    // Log success
    logger.Debug("new_stage complete", "page", info.PageNum)

    // Generate dependent work units if any
    return j.MaybeStartDependentStage(ctx, info.PageNum, state)
}
```

### Step 5: Add to OnComplete Switch

```go
// internal/jobs/process_book/job/job.go - OnComplete()
switch info.UnitType {
// ... existing cases

case WorkUnitTypeNewStage:
    units, handlerErr = j.HandleNewStageComplete(ctx, info, result)
}
```

### Step 6: Add Error Handling

```go
// internal/jobs/process_book/job/job.go - OnComplete() error section
if !result.Success {
    switch info.UnitType {
    // ... existing cases

    case WorkUnitTypeNewStage:
        // Page-level: retry if under limit
        if info.RetryCount < MaxPageOpRetries {
            retryUnit := j.createRetryUnit(ctx, info, logger)
            j.RemoveWorkUnit(result.WorkUnitID)
            return []jobs.WorkUnit{*retryUnit}, nil
        }
        // or for book-level:
        // j.Book.NewStageOp.Fail(MaxBookOpRetries)
        // j.PersistNewStageState(ctx)
    }
}
```

### Step 7: Add Trigger Logic

**For page-level (in GeneratePageWorkUnits or handler):**
```go
// After some precondition met
if state.IsBlendComplete() && !state.IsNewStageDone() {
    unit := j.CreateNewStageWorkUnit(ctx, pageNum, state)
    if unit != nil {
        units = append(units, *unit)
    }
}
```

**For book-level (in MaybeStartBookOperations):**
```go
// internal/jobs/process_book/job/state.go
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
    // ... existing triggers

    // New stage trigger
    if j.SomePrecondition() && j.Book.NewStageOp.CanStart() {
        if err := j.Book.NewStageOp.Start(); err == nil {
            unit := j.CreateNewStageWorkUnit(ctx)
            if unit != nil {
                units = append(units, *unit)
            }
        }
    }

    return units
}
```

### Step 8: Add Persistence Helper

```go
// internal/jobs/common/persist.go
func SaveNewStageResult(ctx context.Context, state *PageState, result jobs.WorkResult) error {
    sink := svcctx.DefraSinkFrom(ctx)

    // Parse result
    parsed := result.ChatResult.ParsedJSON
    value := parsed["new_field"].(string)

    // Write-through to memory
    state.SetNewStageResult(value)

    // Async to DB
    sink.Send(defra.WriteOp{
        Op:         defra.OpUpdate,
        Collection: "Page",
        DocID:      state.DocID,
        Document: map[string]any{
            "new_stage_result":   value,
            "new_stage_complete": true,
        },
    })

    return nil
}
```

### Step 9: Add Prompt Keys (if LLM-based)

```go
// internal/jobs/process_book/job/prompts.go
var promptKeys = []string{
    // ... existing keys
    new_stage_prompt.SystemPromptKey,
    new_stage_prompt.UserPromptKey,
}
```

### Step 10: Update DefraDB Schema (if new fields)

```graphql
# internal/schema/schemas/page.graphql
type Page {
    # ... existing fields
    new_stage_result: String
    new_stage_complete: Boolean
}
```

**Remember:** No `!` (NonNull) in DefraDB schemas.

---

## Modifying Existing Stages

### Change Trigger Threshold

```go
// internal/jobs/process_book/job/types.go
const BlendThresholdForMetadata = 25  // was 20
```

### Add Output Field

1. Update result parsing:
```go
// internal/jobs/common/blend.go - SaveBlendResult()
newField := parsed["new_output"].(string)
state.SetBlendResultWithNewField(text, headings, newField)
```

2. Update persistence:
```go
sink.Send(defra.WriteOp{
    Document: map[string]any{
        "blend_markdown": text,
        "new_output":     newField,  // Add field
    },
})
```

3. Update schema:
```graphql
type Page {
    new_output: String
}
```

### Change Stage Ordering

Modify trigger conditions in `state.go`:
```go
// Old: label triggers after blend only
if state.IsBlendComplete() && !state.IsLabelDone() { ... }

// New: label triggers after blend AND pattern analysis
if state.IsBlendComplete() &&
   j.Book.PatternAnalysis.IsDone() &&
   !state.IsLabelDone() { ... }
```

### Add Input Context

```go
// Pass additional context to work unit
unit := common.CreateLabelWorkUnit(ctx, Input{
    BlendMarkdown:   state.GetBlendMarkdown(),
    PatternContext:  j.Book.GetPatternAnalysisResult(),  // New context
})
```

### Change Retry Policy

```go
// For a specific stage
case WorkUnitTypeNewStage:
    if info.RetryCount < 5 {  // Custom limit for this stage
        retryUnit := j.createRetryUnit(ctx, info, logger)
        // ...
    }
```

---

## Common Patterns

### Page-Level vs Book-Level

| Aspect | Page-Level | Book-Level |
|--------|------------|------------|
| Parallelism | One unit per page | One unit total |
| State | PageState fields | BookState + OperationState |
| Trigger | Per-page completion | Threshold/aggregation |
| Retry | RetryCount in WorkUnitInfo | OperationState.Fail() |
| Example | OCR, Blend, Label | Metadata, ToC Finder |

### Agent-Based Stage

For stages requiring multi-turn LLM interaction:

```go
// Create agent once
j.MyAgent = agents.NewMyAgent(ctx, cfg)

// Work unit just carries LLM request
unit := j.CreateAgentWorkUnit(ctx, j.MyAgent.GetNextRequest())

// On completion, feed back to agent
j.MyAgent.HandleLLMResult(result)

if j.MyAgent.IsDone() {
    // Extract final result
    return j.HandleAgentComplete(ctx)
}

// Not done, continue loop
return j.CreateAgentWorkUnit(ctx, j.MyAgent.GetNextRequest())
```

### Sub-Job Integration

For complex multi-phase operations:

```go
// Start sub-job inline
func (j *Job) StartSubJobInline(ctx context.Context) []jobs.WorkUnit {
    j.SubJob = subjob.NewJob(ctx, j.Book, j.RecordID)
    units, _ := j.SubJob.Start(ctx)

    // Register sub-job units with parent tracker
    for _, unit := range units {
        j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
            UnitType: WorkUnitTypeSubJobPhase,
        })
    }
    return units
}

// Route sub-job completions
func (j *Job) HandleSubJobComplete(ctx, info, result) {
    units, _ := j.SubJob.OnComplete(ctx, result)

    if j.SubJob.Done() {
        return j.MaybeStartNextStage(ctx)
    }
    return units
}
```

### Conditional Stage

For stages that may not apply to all books:

```go
// Check if stage should run
if !j.Book.GetTocFound() {
    // Skip ToC extraction if no ToC found
    j.Book.TocExtract.Skip()  // Custom method to mark as N/A
    return j.MaybeStartNextStage(ctx)
}

// Otherwise proceed normally
return j.CreateTocExtractWorkUnit(ctx)
```
