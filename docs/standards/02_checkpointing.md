# Checkpointing Patterns

**Purpose**: Define how stages implement resume capability and preserve progress across failures.

---

## Overview

The checkpoint system is the foundation of our defensive programming approach. It enables:

- **Resume after crashes** - Don't lose 13 minutes of work on page 380/447
- **Cost tracking** - Accumulate costs across multiple runs
- **Progress monitoring** - External tools can read checkpoint status
- **Validation** - Verify outputs exist and are valid before marking complete

**Core principle:** Checkpoints are the **source of truth** for what's completed. Not in-memory state, not logs - the checkpoint file.

---

## 1. Checkpoint Initialization

### 1.1 Setup Pattern

Every stage initializes a CheckpointManager in `__init__()`:

```python
if enable_checkpoints:
    from checkpoint import CheckpointManager

    self.checkpoint = CheckpointManager(
        scan_id=scan_id,
        stage="stage_name",           # e.g., "ocr", "correction", "fix"
        storage_root=self.storage_root,
        output_dir="output_directory"  # e.g., "corrected", "ocr", "structured"
    )
```

**Key parameters:**
- `stage` - Unique name for this stage's checkpoint
- `output_dir` - Where to find output files for validation

**See implementations:**
- `checkpoint.py` (CheckpointManager class)
- `pipeline/correct.py` (correction stage checkpoint setup)
- `pipeline/fix.py` (fix stage checkpoint setup)

### 1.2 Initialization Principles

**Principle: Load Existing Costs**

After creating checkpoint manager:
```python
checkpoint_state = self.checkpoint.get_status()
existing_cost = checkpoint_state.get('metadata', {}).get('total_cost_usd', 0.0)

self.stats = {
    "total_cost_usd": existing_cost  # START with previous runs!
}
```

**Why critical?** Stages may run multiple times:
- Resume after crash on page 380
- Re-run subset for testing (pages 1-50)
- Fix specific pages after manual review

Each run adds cost. We must **accumulate**, never reset to 0.

**Principle: Checkpoint File Location**

Checkpoints live in: `~/Documents/book_scans/<scan_id>/checkpoints/<stage>.json`

**Why this location?**
- Per-book isolation (each book has own checkpoints)
- Per-stage granularity (OCR independent from correction)
- Atomic updates (temp file → atomic rename)
- Survives process restarts

**See implementations:**
- `checkpoint.py` (file path setup)
- `pipeline/correct.py` (loading existing cost)

---

## 2. Output Validation

### 2.1 Schema-Based Validation

CheckpointManager validates outputs **before** marking pages complete.

**Validation flow:**
1. Output file exists at expected path
2. File contains valid JSON
3. JSON validates against stage output schema
4. Data structure is complete (not partial/corrupted)

**Note:** This will use the schema system being implemented in refactor (#44, #45). Each stage defines its output schema, checkpoint validates against it.

**See future implementation:**
- Schema definitions will live with stages (co-located)
- `checkpoint.py` will accept schema validator in constructor
- Validation becomes: `schema.validate(data)` not ad-hoc field checks

### 2.2 Validation Principles

**Principle: Trust But Verify**

On resume, checkpoint scans output directory to verify completions:
```python
valid_pages = checkpoint.scan_existing_outputs(total_pages)
# Returns Set of page numbers with valid outputs
```

**Why scan on resume?**
- User might have deleted corrupted outputs
- File system might have issues
- Better to re-process than assume completion

**Principle: Schema Validation at Boundaries**

Use schemas to validate structure:
- Parse JSON successfully
- Validate against stage output schema
- Verify required fields present and correctly typed
- Ensure no placeholder/sentinel values

**Why schema validation?**
- Catches incomplete writes (crash during JSON save)
- Detects corrupted files (disk errors, encoding issues)
- Prevents propagating bad data to next stage
- Single source of truth for expected structure

**See current implementation:**
- `checkpoint.py` (`validate_page_output()` - will be refactored to use schemas)
- `checkpoint.py` (`scan_existing_outputs()` - scans and validates)

---

## 3. Resume Capability

### 3.1 Getting Remaining Pages

Standard resume pattern:
```python
if self.checkpoint and resume:
    page_numbers = self.checkpoint.get_remaining_pages(
        total_pages=total_pages,
        resume=True,
        start_page=start_page,
        end_page=end_page
    )
```

**What `get_remaining_pages()` does:**
1. Scans output directory for valid completed pages
2. Updates checkpoint state with validated pages
3. Returns list of pages needing processing in requested range

**See implementation:**
- `checkpoint.py` (`get_remaining_pages()` method)

### 3.2 Resume Principles

**Principle: Output Directory is Source of Truth**

Checkpoint state syncs with actual file presence:
```python
# In get_remaining_pages():
valid_outputs = self.scan_existing_outputs(total_pages)
self._state['completed_pages'] = sorted(list(valid_outputs))
```

**Why sync on resume?**
- User might manually delete bad outputs
- Checkpoint file might be stale
- File system state is ground truth

**Principle: Log Resume Information**

Always tell user what's being skipped:
```python
skipped = (end_page - start_page + 1) - len(page_numbers)
if skipped > 0:
    cost_saved = self.checkpoint.estimate_cost_saved()
    logger.info(f"Resuming: {skipped} pages completed, ~${cost_saved:.2f} saved")
    print(f"✅ Resuming: {skipped} pages completed")
```

**Why log resume info?**
- User visibility (15 min job → 2 min on resume)
- Cost transparency (saved $8 by resuming)
- Debugging (why is nothing processing?)

**Principle: Reset on Fresh Start**

If `resume=False` with checkpointing enabled:
```python
elif self.checkpoint:
    self.checkpoint.reset()  # Clear old state
    page_numbers = list(range(start_page, end_page + 1))
```

**Why explicit reset?**
- Clear stale state from previous runs
- Prevents confusion about what's completed
- User opted out of resume (intentional fresh start)

**See implementations:**
- `pipeline/correct.py` (resume with logging)
- `checkpoint.py` (`get_remaining_pages()` method)

---

## 4. Marking Progress

### 4.1 Page Completion

After successfully saving a page output:
```python
self._save_page_output(page_num, result)  # Save FIRST

if self.checkpoint:
    self.checkpoint.mark_completed(page_num)  # Then mark
```

**Order matters:** Save → Mark (never mark → save)

**See implementation:**
- `checkpoint.py` (`mark_completed()` method)

### 4.2 Page Completion Principles

**Principle: Save Before Mark**

Always save output file before marking checkpoint:
- If save fails → exception → page stays incomplete
- If mark fails → page stays incomplete (safe to retry)
- Never mark page complete with no output

**Principle: Thread-Safe Updates**

`mark_completed()` is thread-safe:
- Internal lock protects checkpoint state
- Can be called from parallel workers
- No race conditions

**Principle: Save on Every Completion**

Checkpoint saves after each page is marked complete:
```python
# In mark_completed():
self._save_checkpoint()
```

**Why save every time?**
- Operations are already slow (LLM calls take seconds)
- No performance impact from frequent writes
- Zero lost work on crash (every completed page recorded)
- Simpler than batching logic

---

## 5. Stage Completion

### 5.1 Marking Complete

After successful processing:
```python
if self.checkpoint:
    self.checkpoint.mark_stage_complete(metadata={
        "model": self.model,
        "pages_processed": pages_processed,
        "total_cost_usd": self.stats['total_cost_usd']  # ACCUMULATED cost
    })
```

**See implementation:**
- `checkpoint.py` (`mark_stage_complete()` method)

### 5.2 Completion Principles

**Principle: Save Accumulated Costs**

The `total_cost_usd` in metadata is cumulative across all runs:
- First run: $8.50
- Resume run: adds $1.20 → metadata shows $9.70
- Next resume: adds $0.50 → metadata shows $10.20

**Why accumulate?**
- Accurate total cost for the book
- Cost estimation for similar books
- Budget tracking

**Principle: Flush Pending Updates**

`mark_stage_complete()` saves any pending page completions:
```python
# Inside mark_stage_complete():
self._save_checkpoint()  # Flush pending pages FIRST
self._state['status'] = 'completed'
self._save_checkpoint()  # Save completion status
```

**Why flush first?**
- Pages completed since last incremental save (every 5 pages)
- Ensures all work is recorded
- Critical for accurate resume

**Principle: Include Processing Metadata**

Save useful metadata for analysis:
- Model used (reproducibility)
- Pages processed this run
- Total accumulated cost
- Duration (tracked automatically)

**See implementations:**
- `checkpoint.py` (`mark_stage_complete()` method)
- `pipeline/correct.py` (usage in correction stage)

---

## 6. Failure Handling

### 6.1 Marking Failed

On stage-level exception:
```python
try:
    self._process_all_pages(page_numbers)
    self.checkpoint.mark_stage_complete(metadata={...})
except Exception as e:
    if self.checkpoint:
        self.checkpoint.mark_stage_failed(error=str(e))
    raise  # Re-raise after marking
```

**See implementation:**
- `checkpoint.py` (`mark_stage_failed()` method)

### 6.2 Failure Principles

**Principle: Preserve Partial Progress**

Failed status doesn't erase completed pages:
- Pages successfully processed stay marked complete
- Can resume from failure point
- No wasted work

**Principle: Record Error Context**

Save error message in checkpoint:
```python
self._state['status'] = 'failed'
self._state['error'] = error
self._state['failed_at'] = datetime.now().isoformat()
```

**Why record error?**
- Debugging (what went wrong?)
- Monitoring (external tools can detect)
- User visibility (clear failure reason)

**Principle: Re-raise After Marking**

Don't swallow exceptions:
```python
self.checkpoint.mark_stage_failed(error=str(e))
raise  # Let caller handle
```

**Why re-raise?**
- Caller might have recovery logic
- Pipeline needs to know stage failed
- Logs capture full stack trace

**See implementations:**
- `pipeline/structure/__init__.py` (failure handling in process_book)
- `checkpoint.py` (`mark_stage_failed()` method)

---

## 7. Atomic Updates

### 7.1 Atomic Write Pattern

Checkpoints use atomic writes to prevent corruption:

1. Write to temp file: `<stage>.json.tmp`
2. Validate temp file (parse JSON)
3. Atomic rename: `tmp` → `<stage>.json`

**Why atomic?**
- Crash during write → temp file, checkpoint unchanged
- Never have partial/corrupted checkpoint
- File system guarantees rename atomicity

**See implementation:**
- `checkpoint.py` (`_save_checkpoint()` method)

### 7.2 Atomic Update Principles

**Principle: Temp File → Validate → Rename**

Always validate before replacing:
```python
# Write to temp
with open(temp_file, 'w') as f:
    json.dump(state, f)
    f.flush()
    os.fsync(f.fileno())  # Force OS write

# Validate
with open(temp_file) as f:
    json.load(f)  # Throws if corrupt

# Atomic rename
temp_file.replace(checkpoint_file)
```

**Principle: Cleanup Orphaned Temp Files**

On initialization, clean up stale temp files:
```python
# In __init__:
self._cleanup_temp_files()  # Remove *.json.tmp* from crashes
```

**Why cleanup?**
- Crashes can leave temp files
- Prevents accumulation
- No impact if cleanup fails (best effort)

**See implementation:**
- `checkpoint.py` (`_cleanup_temp_files()` method)

---

## Summary

A production-ready checkpoint system:

1. ✅ Validates outputs using schemas (prevents propagating bad data)
2. ✅ Syncs checkpoint state with output directory on resume
3. ✅ Accumulates costs across multiple runs (never resets)
4. ✅ Saves before marking (never mark without output)
5. ✅ Thread-safe for parallel workers
6. ✅ Saves on every completion (no batching needed)
7. ✅ Preserves partial progress on failures
8. ✅ Uses atomic writes (temp → validate → rename)
9. ✅ Logs resume information for user visibility
10. ✅ Records metadata for analysis and reproduction

---

## Next Steps

Continue to [03_llm_client.md](03_llm_client.md) to understand LLM API patterns and structured outputs with schemas.
