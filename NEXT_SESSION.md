# Next Session: Propagate Retry & Output Improvements Through Label Stage

## Context

This session completed major improvements to retry logic and terminal output for the correction stage. These patterns should be propagated to OCR and Label stages.

## Completed This Session

### 1. Fixed Logger Console Output (Commit 4a479c0)
**Problem:** Logger timestamps/errors printing to stdout, breaking progress bars

**Fix:** Disabled console output for correction stage logger:
```python
self.logger = create_logger(book_title, "correction", log_dir=logs_dir, console_output=False)
```

**Result:** Clean progress bars without logger interference

### 2. Refactored Retry Architecture (Commit ca75782)
**Old architecture problems:**
- Multiple retry layers: LLM client (3×) + Stage (10×) = 30 attempts!
- Progress bar finished, then invisible retry loop
- Stage marked "complete" even with failures
- Incorrect cost/stats tracking

**New architecture:**
```python
# Single-pass retry with accumulation
max_retries = 3  # Total attempts: initial + 2 retries
pending_tasks = tasks.copy()

while pending_tasks and retry_count < max_retries:
    failed_tasks = []

    # Process batch in parallel
    for task in pending_tasks:
        if success:
            completed += 1
            progress.update(completed, suffix=f"${cost:.2f}")
        else:
            failed_tasks.append(task)  # Accumulate

    # Retry failed batch after delay
    if failed_tasks:
        retry_count += 1
        pending_tasks = failed_tasks
        delay_and_retry()

# Only mark complete when ALL pages succeed
if errors == 0:
    mark_stage_complete()
else:
    print_failed_pages_and_resume_command()
```

**Benefits:**
- Single progress bar tracking total pages
- Progress only increments on success
- Failures accumulate, retry entire batch
- Clear retry count (3 attempts vs 30!)
- Stage marked complete only when done
- Clean cost/stats throughout

### 3. Cleaned Progress Bar Output (Commit 0e785fa)
**Before (redundant):**
```
65% (401/616) - 1.3 pages/sec - 391 ok, $0.41, 10 failed
```

**After (clean):**
```
First pass:
65% (401/616) - 1.3 pages/sec - $0.41

Retrying:
65% (401/616) - 1.3 pages/sec - $0.41 (attempt 2/3)
```

**Removed:**
- "X ok" (redundant with progress count)
- "X pending/failed" (shown in retry message)

**Added:**
- "(attempt X/Y)" indicator when retrying

### 4. Unified Terminal Output (Commit 6220499)
**Created:**
- `infra/progress.py` - Reusable ProgressBar utility
- `docs/standards/10_terminal_output.md` - Terminal output standards

**Applied to:**
- `tools/add.py` (book ingestion)
- `pipeline/2_correction/` (correction stage)

**Standards:**
- Stage entry: `🔧 Stage Name (scan-id)`
- Clean progress bars with ETA
- 3-space indentation for operations
- Stage exit: `✅ Stage complete: X/Y pages`
- Errors on new lines (don't break progress)

## Current State

### Stages with New Patterns ✅
- ✅ **Stage 0 (Ingest):** Clean output with ProgressBar
- ✅ **Stage 2 (Correction):** Retry refactor + clean output

### Stages Needing Updates ⚠️
- ⚠️ **Stage 1 (OCR):** Still has old retry patterns
- ⚠️ **Stage 3 (Label):** Not yet implemented

## Next Steps

### Priority 1: Update OCR Stage Retry Logic

**File:** `pipeline/1_ocr/__init__.py`

**Current issues:**
- Uses old retry patterns (similar to what correction had)
- Progress tracking may have redundant info
- Logger console output may interfere with progress

**Apply same fixes:**

1. **Disable logger console output** (line ~104):
```python
self.logger = create_logger(book_title, "ocr", log_dir=logs_dir, console_output=False)
```

2. **Refactor retry logic** (lines ~393-442):
- Remove any multi-layer retry loops
- Implement single-pass batch retry
- Track failures, accumulate, retry batch
- Progress updates only on success
- Mark complete only when errors == 0

3. **Clean progress bar suffix**:
- Remove redundant "X ok" if present
- Show just cost (if applicable) + attempt indicator
- Format: `${cost:.2f} (attempt 2/3)` when retrying

**Reference:**
- Use `pipeline/2_correction/__init__.py` as template
- Lines 225-337 show the pattern

### Priority 2: Implement Label Stage (Stage 3)

**Purpose:** Block classification and page number extraction

**File to create:** `pipeline/3_label/__init__.py`

**Apply patterns from day 1:**

1. **Logger setup:**
```python
self.logger = create_logger(book_title, "label", log_dir=logs_dir, console_output=False)
```

2. **Progress tracking:**
```python
from infra.progress import ProgressBar

progress = ProgressBar(
    total=len(tasks),
    prefix="   ",
    width=40,
    unit="pages"
)
```

3. **Retry logic:**
```python
max_retries = 3
pending_tasks = tasks.copy()

while pending_tasks and retry_count < max_retries:
    # Process batch, accumulate failures
    # Retry failed batch after delay
```

4. **Terminal output:**
```python
# Stage entry
print(f"\n🏷️  Label Stage ({book_title})")
print(f"   Pages:     {total_pages}")
print(f"   Workers:   {self.max_workers}")
print(f"   Model:     {self.model}")

# Progress updates
progress.update(completed, suffix=f"${cost:.2f}")

# Stage exit (only if all succeed)
if errors == 0:
    print(f"\n✅ Label complete: {completed}/{total_pages} pages")
```

### Priority 3: Test End-to-End

**Test book:** `right-wing-critics` (currently has 5 failed pages in correction)

**Steps:**
1. Update OCR stage retry logic
2. Test OCR on a fresh book
3. Verify clean output, proper retry behavior
4. Implement Label stage with same patterns
5. Run full pipeline: Ingest → OCR → Correction → Label
6. Verify all stages have consistent output

## Expected Output Format (All Stages)

### Stage Entry
```
🔧 Stage Name (scan-id)
   Pages:     371
   Workers:   30
   Model:     google/gemini-2.5-flash-lite-preview-09-2025
```

### Processing
```
   Processing 371 pages...
   [████████████████████░░░░░░░░] 80% (297/371) - 1.2 pages/sec - ETA 1m 2s - $0.30
```

### Retry (if needed)
```
   ⚠️  15 page(s) failed, retrying after 10s (attempt 2/3)...
   [█████████████████████████░░░] 95% (352/371) - 1.1 pages/sec - ETA 17s - $0.35 (attempt 2/3)
```

### Stage Exit (Success)
```
   ✓ 371/371 pages processed

✅ Stage complete: 371/371 pages
   Total cost: $0.37
   Avg per page: $0.001
```

### Stage Exit (Incomplete)
```
   ✓ 366/371 pages processed
   ⚠️  5 pages failed: [150, 269, 273, 283, 351]

⚠️  Stage incomplete: 366/371 pages succeeded
   Total cost: $0.37
   Failed pages: [150, 269, 273, 283, 351]

   To retry failed pages:
   uv run python ar.py process [stage] [scan-id] --resume
```

## Key Principles

### Retry Logic
- **Single-pass batch retry** - No multi-layer confusion
- **3 attempts max** - Initial + 2 retries
- **Accumulate failures** - Retry entire batch together
- **Clear indicators** - "(attempt X/Y)" in progress suffix
- **Complete only when done** - Don't mark complete with failures

### Progress Bars
- **Single line** - Carriage return updates
- **Minimal suffix** - Just cost + attempt indicator
- **No redundancy** - Progress count shows completion
- **ETA included** - Built into ProgressBar utility

### Terminal Output
- **Consistent formatting** - 3-space indentation
- **Clear boundaries** - Stage entry/exit markers
- **Error isolation** - New lines don't break progress
- **No logger spam** - Console output disabled

### Cost Tracking
- **Thread-safe** - Use stats_lock
- **Per-page tracking** - Checkpoint includes cost
- **Cumulative** - Resume runs add to existing cost
- **Stage summary** - Total + avg per page

## File Reference

**Patterns to copy:**
- `pipeline/2_correction/__init__.py` - Retry logic (lines 225-337)
- `infra/progress.py` - Progress bar utility
- `docs/standards/10_terminal_output.md` - Output standards

**Files to update:**
- `pipeline/1_ocr/__init__.py` - Apply retry refactor
- `pipeline/3_label/__init__.py` - Create with patterns

## Testing Checklist

After updating OCR stage:
- [ ] Single progress bar (no multiple bars)
- [ ] Progress only increments on success
- [ ] Retry indicator shows when retrying
- [ ] No logger stdout spam
- [ ] Stage marked complete only when done
- [ ] Failed pages show resume command
- [ ] Cost tracking accurate on resume

After implementing Label stage:
- [ ] Follows same retry pattern
- [ ] Clean terminal output
- [ ] Consistent with other stages
- [ ] Tests pass end-to-end

## Architecture Notes

**Retry Pattern:**
```python
# Key insight: Progress tracks SUCCESS, not attempts
# Failures accumulate, retry batch together

while pending_tasks and retry_count < max_retries:
    for task in pending_tasks:
        result = process(task)
        if result.success:
            completed += 1  # Only increment on success!
            progress.update(completed)
        else:
            failed_tasks.append(task)

    pending_tasks = failed_tasks  # Retry failures
```

**Progress Bar Pattern:**
```python
# Minimal suffix, clear retry indicator
suffix = f"${total_cost:.2f}"
if retry_count > 0:
    suffix += f" (attempt {retry_count + 1}/{max_retries})"
progress.update(completed, suffix=suffix)
```

**Stage Completion Pattern:**
```python
# Only mark complete if ALL pages succeeded
if errors == 0:
    checkpoint.mark_stage_complete()
    metadata['stage_complete'] = True
else:
    # Leave checkpoint in_progress
    # Print failed pages + resume command
```

## Cost Tracking

**Current costs (per page):**
- OCR: ~$0 (Tesseract, free)
- Correction: ~$0.001 (Gemini 2.5 Flash Lite)
- Label: ~$0.0005 (estimated, simpler task)

**Estimated total per book (300 pages):**
- OCR: $0
- Correction: $0.30
- Label: $0.15
- **Total: ~$0.45 per book**

## Commit Strategy

**Commit 1:** Update OCR stage retry logic
- Disable logger console output
- Refactor retry to single-pass batch
- Clean progress bar suffix
- Test on fresh book

**Commit 2:** Implement Label stage with patterns
- Create `pipeline/3_label/__init__.py`
- Follow retry/output patterns from correction
- Integrate with pipeline flow
- Test end-to-end

## References

- Terminal Output Standards: `docs/standards/10_terminal_output.md`
- Progress Bar Utility: `infra/progress.py`
- Retry Pattern Example: `pipeline/2_correction/__init__.py` (lines 225-337)
- Current branch: `refactor/pipeline-redesign`
- Recent commits: 6220499 (terminal output), 0e785fa (progress cleanup), ca75782 (retry refactor)

---

**Start next session:**
1. Read this file for context
2. Apply retry refactor to OCR stage
3. Test OCR on fresh book
4. Implement Label stage with same patterns
5. Test full pipeline end-to-end
