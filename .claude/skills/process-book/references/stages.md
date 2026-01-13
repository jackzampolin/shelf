# Stage Patterns

> **Note:** Specific stages in the pipeline may change over time. This document focuses on the **patterns** used to implement stages, which are stable.

## Table of Contents
- [Stage Categories](#stage-categories)
- [Page-Level Stage Pattern](#page-level-stage-pattern)
- [Book-Level Stage Pattern](#book-level-stage-pattern)
- [Agent-Based Stage Pattern](#agent-based-stage-pattern)
- [Multi-Phase Stage Pattern](#multi-phase-stage-pattern)
- [Sub-Job Pattern](#sub-job-pattern)
- [Cascading Trigger Pattern](#cascading-trigger-pattern)

---

## Stage Categories

| Category | Parallelism | State Location | Example Uses |
|----------|-------------|----------------|--------------|
| Page-level | Per-page parallel | PageState | OCR, blend, label |
| Book-level | One at a time | BookState + OperationState | Metadata, ToC finder |
| Agent-based | Stateful loop | Agent struct | Multi-turn LLM tasks |
| Multi-phase | Sequential phases | BookState partitions | Pattern analysis |
| Sub-job | Embedded job | Sub-job state | Complex multi-stage ops |

---

## Page-Level Stage Pattern

For operations that run independently per page.

### Structure

```go
// 1. Create work unit
func (j *Job) CreatePageStageWorkUnit(ctx context.Context, pageNum int, state *common.PageState) *jobs.WorkUnit {
    input := stage.Input{
        PageNum: pageNum,
        // ... page-specific data
    }

    unit := common.CreatePageStageWorkUnit(ctx, j, input)
    if unit == nil {
        return nil
    }

    j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
        UnitType: WorkUnitTypePageStage,
        PageNum:  pageNum,
    })
    return unit
}

// 2. Handle completion
func (j *Job) HandlePageStageComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
    state := j.Book.Pages[info.PageNum]

    // Save result (write-through)
    if err := common.SavePageStageResult(ctx, state, result); err != nil {
        return nil, err
    }

    // Generate next stage work units
    return j.MaybeGenerateNextUnits(ctx, info.PageNum, state)
}
```

### Characteristics
- One work unit per page
- State in `PageState` (per-page struct)
- Triggers next stage when this page completes
- Retries tracked in `WorkUnitInfo.RetryCount`

---

## Book-Level Stage Pattern

For operations that run once for the whole book.

### Structure

```go
// 1. Trigger check (in MaybeStartBookOperations)
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
    // Check threshold/precondition
    if j.SomeThresholdMet() && j.Book.SomeOp.CanStart() {
        if err := j.Book.SomeOp.Start(); err == nil {
            unit := j.CreateBookStageWorkUnit(ctx)
            if unit != nil {
                return []jobs.WorkUnit{*unit}
            }
        }
    }
    return nil
}

// 2. Create work unit
func (j *Job) CreateBookStageWorkUnit(ctx context.Context) *jobs.WorkUnit {
    input := stage.Input{
        // ... book-level data
    }

    unit := common.CreateBookStageWorkUnit(ctx, j, input)
    j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
        UnitType: WorkUnitTypeBookStage,
    })
    return unit
}

// 3. Handle completion
func (j *Job) HandleBookStageComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
    // Save result
    if err := common.SaveBookStageResult(ctx, j.Book, result); err != nil {
        return nil, err
    }

    // Mark complete
    j.Book.SomeOp.Complete()
    j.PersistBookStageState(ctx)

    // Check for next book operations
    return j.MaybeStartBookOperations(ctx)
}
```

### Characteristics
- Single work unit for entire book
- State in `BookState` with `OperationState` wrapper
- Triggered by thresholds (e.g., "20 pages blended")
- Retries tracked in `OperationState.RetryCount`

### OperationState API

```go
op.CanStart()   // true if OpNotStarted
op.Start()      // NotStarted → InProgress
op.Complete()   // InProgress → Complete
op.Fail(max)    // Increment retry, maybe → Failed
op.IsStarted()  // InProgress or Complete
op.IsDone()     // Complete or permanently Failed
op.Reset()      // Back to NotStarted
```

---

## Agent-Based Stage Pattern

For multi-turn LLM interactions with tool use.

### Structure

```go
// 1. Create agent (once)
func (j *Job) StartAgentStage(ctx context.Context) *jobs.WorkUnit {
    j.MyAgent = agents.NewMyAgent(ctx, agents.Config{
        Debug: j.Book.DebugAgents,
        JobID: j.RecordID,
    })

    return j.CreateAgentWorkUnit(ctx)
}

// 2. Create work unit for current agent step
func (j *Job) CreateAgentWorkUnit(ctx context.Context) *jobs.WorkUnit {
    request := j.MyAgent.GetNextRequest()

    unit := &jobs.WorkUnit{
        ID:      uuid.New().String(),
        Type:    jobs.WorkUnitTypeChat,
        Request: request,
    }

    j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
        UnitType: WorkUnitTypeAgentStage,
    })
    return unit
}

// 3. Handle LLM response
func (j *Job) HandleAgentComplete(ctx context.Context, info WorkUnitInfo, result jobs.WorkResult) ([]jobs.WorkUnit, error) {
    // Feed result to agent
    j.MyAgent.HandleLLMResult(result)

    // Check if agent is done
    if j.MyAgent.IsDone() {
        // Save agent log if debug enabled
        if j.Book.DebugAgents {
            j.MyAgent.SaveLog(ctx)
        }

        // Extract result and proceed
        agentResult := j.MyAgent.Result()
        return j.HandleAgentResult(ctx, agentResult)
    }

    // Execute tool loop (if agent wants to call tools)
    if action := agents.ExecuteToolLoop(j.MyAgent); action != nil {
        // Tool executed, agent may have more work
    }

    // Continue with next LLM call
    return []jobs.WorkUnit{*j.CreateAgentWorkUnit(ctx)}, nil
}
```

### Characteristics
- Agent struct holds conversation state
- Multiple LLM round-trips per logical operation
- Tool calls executed synchronously in `ExecuteToolLoop`
- Logs saved to DefraDB when `DebugAgents=true`

---

## Multi-Phase Stage Pattern

For operations with parallel phases followed by aggregation.

### Structure

```go
// Phase 1: Launch parallel sub-operations
func (j *Job) StartMultiPhaseStage(ctx context.Context) []jobs.WorkUnit {
    var units []jobs.WorkUnit

    // Phase 1a
    unit1 := j.CreatePhase1aWorkUnit(ctx)
    j.RegisterWorkUnit(unit1.ID, WorkUnitInfo{
        UnitType: WorkUnitTypePhase1a,
    })
    units = append(units, *unit1)

    // Phase 1b (parallel with 1a)
    unit2 := j.CreatePhase1bWorkUnit(ctx)
    j.RegisterWorkUnit(unit2.ID, WorkUnitInfo{
        UnitType: WorkUnitTypePhase1b,
    })
    units = append(units, *unit2)

    return units
}

// Handle phase completions
func (j *Job) HandlePhase1aComplete(ctx, info, result) {
    j.Book.SetPhase1aResult(result)  // Thread-safe

    // Check if all phase 1 done
    if j.AllPhase1Complete() {
        return j.StartPhase2(ctx)
    }
    return nil
}

func (j *Job) HandlePhase1bComplete(ctx, info, result) {
    j.Book.SetPhase1bResult(result)  // Thread-safe

    if j.AllPhase1Complete() {
        return j.StartPhase2(ctx)
    }
    return nil
}

// Phase 2: Sequential after phase 1
func (j *Job) StartPhase2(ctx context.Context) []jobs.WorkUnit {
    unit := j.CreatePhase2WorkUnit(ctx)
    // Uses results from phase 1a and 1b
    return []jobs.WorkUnit{*unit}
}
```

### Characteristics
- Multiple parallel work units in phase 1
- Thread-safe setters for partial results
- Phase 2 triggered when all phase 1 complete
- Final aggregation combines all results

---

## Sub-Job Pattern

For complex operations that deserve their own job structure.

### Structure

```go
// 1. Start sub-job inline
func (j *Job) StartSubJobInline(ctx context.Context) []jobs.WorkUnit {
    // Create sub-job with parent's context
    j.SubJob = subjob.NewJob(ctx, subjob.Config{
        Book:     j.Book,
        RecordID: j.RecordID,  // Share parent's record ID
    })

    // Get initial work units from sub-job
    units, err := j.SubJob.Start(ctx)
    if err != nil {
        return nil
    }

    // Register sub-job units with parent's tracker
    for _, unit := range units {
        j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
            UnitType: WorkUnitTypeSubJob,
            SubPhase: unit.Type,
        })
    }
    return units
}

// 2. Route completions to sub-job
func (j *Job) HandleSubJobComplete(ctx, info, result) ([]jobs.WorkUnit, error) {
    // Delegate to sub-job's OnComplete
    units, err := j.SubJob.OnComplete(ctx, result)
    if err != nil {
        return nil, err
    }

    // Check if sub-job finished
    if j.SubJob.Done() {
        return j.MaybeStartNextStage(ctx)
    }

    // Register any new units from sub-job
    for _, unit := range units {
        j.RegisterWorkUnit(unit.ID, WorkUnitInfo{
            UnitType: WorkUnitTypeSubJob,
            SubPhase: unit.Type,
        })
    }
    return units, nil
}
```

### Characteristics
- Sub-job has its own `Start()` and `OnComplete()` methods
- Parent job registers and routes work units
- Shares parent's `RecordID` for tracking
- Sub-job manages its own internal state

---

## Cascading Trigger Pattern

When one stage completion can trigger multiple downstream stages.

### Structure

```go
func (j *Job) MaybeStartBookOperations(ctx context.Context) []jobs.WorkUnit {
    var units []jobs.WorkUnit

    // Trigger 1: After N pages blended → Metadata
    if j.Book.CountBlendedPages() >= ThresholdA && j.Book.Metadata.CanStart() {
        j.Book.Metadata.Start()
        if unit := j.CreateMetadataWorkUnit(ctx); unit != nil {
            units = append(units, *unit)
        }
    }

    // Trigger 2: After M consecutive pages → ToC Finder
    if j.ConsecutiveFromStart() >= ThresholdB && j.Book.TocFinder.CanStart() {
        j.Book.TocFinder.Start()
        if unit := j.CreateTocFinderWorkUnit(ctx); unit != nil {
            units = append(units, *unit)
        }
    }

    // Trigger 3: After ALL pages complete → Analysis
    if j.Book.AllPagesComplete() && j.Book.Analysis.CanStart() {
        j.Book.Analysis.Start()
        if unit := j.CreateAnalysisWorkUnit(ctx); unit != nil {
            units = append(units, *unit)
        }
    }

    return units
}
```

### Call Sites
- From page-level completion handlers (e.g., after blend)
- From book-level completion handlers (chain to next)
- From `Start()` on job resume

### Characteristics
- Single function checks all trigger conditions
- Multiple operations can start simultaneously
- Each trigger is independent (uses `CanStart()`)
- Returns all triggered work units at once
