# Next Session: Apply Stage 2 Patterns to Stage 3 (Merge)

## Context

We just completed a major cleanup of Stage 2 (Correction) across 6 commits:

### Stage 2 Refactor Summary (Commits e81e915 → 514d7f8)

1. **Extracted prompts** → `pipeline/2_correction/prompts.py` (~190 lines)
2. **Simplified logging** → LLM failures to `LLMBatchClient`, removed `infra.logger`
3. **Code review cleanup** → Removed dead code, fixed abstraction leaks, removed dual stats
4. **Extracted callbacks** → `_handle_progress_event()`, `_handle_result()` methods
5. **Simplified checkpoint** → `reset(confirm=True)`, auto-ensure directories
6. **Removed redundant tracking** → Use CheckpointManager/LLMBatchClient as source of truth

**Result:** Correction stage is now ~465 lines of clean, maintainable code with clear separation of concerns.

---

## Next Session Goal

**Apply the same patterns to Stage 3 (Merge)** to bring it up to the same quality standard.

---

## Agent-Driven Refactoring Workflow

### Step 1: Analyze Stage 2 Patterns

Use `@agent-feature-dev:code-explorer` to document the patterns we established:

**Prompt:**
```
Analyze pipeline/2_correction/ to document the patterns and architecture we've established.

Focus on:
1. **File organization** - Where do prompts, schemas, and logic live?
2. **Infrastructure usage** - How does it use CheckpointManager, BookStorage, LLMBatchClient?
3. **Method extraction** - How are callbacks and complex logic organized?
4. **Single source of truth** - Where does data come from (no dual tracking)?
5. **Error handling** - Patterns for defensive errors and logging

Output:
- List of patterns with examples (file:line references)
- Why each pattern exists
- What problems it solves

This will become our "gold standard" for refactoring other stages.
```

### Step 2: Analyze Stage 3 Current State

Use `@agent-feature-dev:code-explorer` to understand Stage 3:

**Prompt:**
```
Analyze pipeline/3_merge/ (or wherever merge stage lives) to understand its current architecture.

Document:
1. **File structure** - What files exist? How is code organized?
2. **Complexity** - Line counts, callback sizes, embedded prompts?
3. **Infrastructure usage** - Does it use CheckpointManager, BookStorage APIs?
4. **Patterns** - Does it match Stage 2 patterns or use old approaches?

Output:
- Current state summary
- Comparison to Stage 2 patterns (what matches, what doesn't)
- Estimated refactoring scope
```

### Step 3: Generate Refactoring Plan

Use `@agent-feature-dev:code-architect` to create the refactoring blueprint:

**Prompt:**
```
Based on Stage 2 patterns and Stage 3 current state, create a refactoring plan.

Apply Stage 2 patterns:
1. Extract prompts to prompts.py (if any LLM calls)
2. Use LLMBatchClient with log_dir for failure logging
3. Use BookStorage/StageView high-level APIs
4. Extract large callbacks to class methods
5. Use CheckpointManager.reset(confirm=True)
6. Single source of truth for all metrics
7. Auto-ensure directories via checkpoint property

Output plan with:
- Step-by-step refactoring sequence
- Files to create/modify
- Estimated line changes per step
- Risk areas (what could break)
- Testing strategy

Break into small, testable commits like we did for Stage 2.
```

### Step 4: Execute Refactoring

Use the plan to refactor Stage 3 in small commits, validating at each step.

After each major change, use `@agent-feature-dev:code-reviewer` to find additional simplifications (like we did for Stage 2).

---

## Key Patterns to Apply (from Stage 2)

### 1. Prompts as First-Class Artifacts
```python
# OLD: Prompts embedded in class methods
class MyStage:
    def _build_prompt(self):
        return """..."""  # 100+ lines

# NEW: Prompts in separate file
# pipeline/N_stage/prompts.py
SYSTEM_PROMPT = """..."""
def build_user_prompt(...): ...
```

### 2. Infrastructure-Driven Logging
```python
# OLD: Stage manages logger
self.logger = create_logger(...)
self.logger.error(...)

# NEW: LLMBatchClient logs failures
self.batch_client = LLMBatchClient(
    log_dir=storage.stage.get_log_dir()  # Logs to stage/logs/llm_failures.jsonl
)
```

### 3. Checkpoint Simplification
```python
# OLD: Manual confirmation logic (~20 lines)
if checkpoint.exists():
    status = checkpoint.get_status()
    print("Progress exists...")
    confirm = input("Continue?")
    if confirm != 'yes': return
checkpoint.reset()

# NEW: Confirmation in CheckpointManager
if not checkpoint.reset(confirm=True):
    return  # User cancelled
```

### 4. Auto-Ensure Directories
```python
# OLD: Manual call
storage.stage.ensure_directories()

# NEW: Automatic on checkpoint access
checkpoint = storage.stage.checkpoint  # Directories created automatically
```

### 5. Extract Large Callbacks
```python
# OLD: 50+ line inline callbacks
def on_event(event):
    # ... 50 lines of logic ...

# NEW: Extracted to methods
def _handle_progress_event(self, event, progress, total):
    # ... logic ...

def on_event(event):
    self._handle_progress_event(event, progress, total)
```

### 6. Single Source of Truth
```python
# OLD: Dual tracking
self.stats = {'total_cost': 0.0}
with self.lock:
    self.stats['total_cost'] += cost

# NEW: Use infrastructure
batch_stats = self.batch_client.get_batch_stats()
total_cost = batch_stats.total_cost_usd  # Single source
```

---

## Deferred Improvements (Future)

These didn't make it into Stage 2 but could be applied later:

### Issue #2 from Last Review (85% confidence)
**Push active request data in EventData** instead of polling `get_active_requests()` in callbacks.

**Why deferred:** Requires LLMBatchClient changes, affects all stages. Better to do after Stage 3 refactor.

**Benefit:** ~5 lines saved per stage, better encapsulation, removes 2 method calls/sec.

---

## Success Criteria

Stage 3 matches Stage 2 quality:
- ✅ Prompts extracted (if applicable)
- ✅ Uses BookStorage/StageView high-level APIs
- ✅ Uses CheckpointManager.reset(confirm=True)
- ✅ Directories auto-ensured
- ✅ Callbacks extracted to methods
- ✅ Single source of truth for all metrics
- ✅ LLM failures logged to stage/logs/llm_failures.jsonl
- ✅ Clear, maintainable code (~similar line count to Stage 2)

---

## Testing Strategy

For each refactoring step:
1. **Run on test book** - Validate output identical to before
2. **Check checkpoint resume** - Ensure resume works correctly
3. **Verify failure handling** - Check llm_failures.jsonl on errors
4. **Compare costs** - Ensure same LLM calls (no duplication/missing)

---

## Timeline Estimate

Based on Stage 2 refactor (6 commits over 1 session):

- **Step 1: Pattern analysis** - 15 min (agent-driven)
- **Step 2: Current state analysis** - 15 min (agent-driven)
- **Step 3: Refactoring plan** - 20 min (agent-driven)
- **Step 4: Execute refactor** - 60-90 min (6-8 commits, testing between)

**Total: ~2-2.5 hours** (similar to Stage 2)

---

## Notes

- Stage 2 is now the "gold standard" reference implementation
- Use agents to analyze and plan, then execute systematically
- Small commits, test frequently
- After Stage 3, repeat for Stage 4 (Structure), Stage 5 (Chunks)
- Eventually all stages will follow the same clean patterns
