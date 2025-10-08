# Stage Interface Patterns

**Purpose**: Define the standard interface that all pipeline stages must implement.

---

## Overview

Every pipeline stage (OCR, Correct, Fix, Structure) follows a common pattern for initialization, processing, and result reporting. This consistency makes stages:

- **Testable** - Can be run standalone with different storage_root
- **Composable** - Can be chained together in the pipeline
- **Observable** - Logger and checkpoint patterns are consistent
- **Configurable** - Model and worker settings can be overridden
- **Resumable** - Can resume from checkpoint after failures
- **Monitorable** - Reports status for external monitoring tools

---

## 1. Standard Initialization

### 1.1 Required Parameters

Every stage `__init__()` MUST accept:

- `scan_id: str` - Unique book identifier (e.g., "modest-lovelace")
- `storage_root: Optional[Path]` - Base directory (default: ~/Documents/book_scans)
- `enable_checkpoints: bool` - Enable checkpoint-based resume (default: True)
- `logger: Optional[PipelineLogger]` - Logger instance (creates new if None)
- `model: Optional[str]` - LLM model override (uses Config if None)
- `max_workers: Optional[int]` - Parallelization override (uses Config if None)

**Why these parameters?**
- `storage_root` - Enables testing with isolated directories
- `enable_checkpoints` - Allows disabling for simple test cases
- `logger` - Supports both standalone (creates own) and pipeline (shared logger)
- `model/max_workers` - Override defaults for experiments/testing

**See examples:**
- `pipeline/correct.py:56-64`
- `pipeline/fix.py:34-38`
- `pipeline/structure/__init__.py:30-35`

### 1.2 Initialization Principles

**Principle: Fail Fast**
- Validate `book_dir` exists immediately in `__init__()`
- Raise `FileNotFoundError` if missing - don't defer to first page
- Better to fail with clear error than mysterious failure later

**Principle: Support Standalone AND Pipeline Use**
- If `logger` provided: Use it (pipeline mode, shared context)
- If `logger` is None: Create new logger (standalone mode)
- Both modes must work identically

**Principle: Model from Config with Override**
- Default: `Config.get_model_for_stage("stage_name")`
- Override: Accept `model` parameter for experiments
- Allows per-stage optimization (cheap vs high-quality models)

**Principle: Accumulate Costs from Checkpoint**
- Load `total_cost_usd` from checkpoint metadata
- Initialize `self.stats['total_cost_usd']` with existing cost
- **Never reset to 0** - stages may run multiple times
- Critical for accurate multi-session cost tracking

**Principle: Thread-Safe Statistics**
- Use `threading.Lock()` for all shared state (`self.stats`)
- Parallel workers update stats concurrently
- Without locking → race conditions and incorrect totals

**See implementations:**
- `pipeline/correct.py:56-110` (full pattern)
- `pipeline/fix.py:34-81` (simpler version)
- `pipeline/structure/__init__.py:30-82` (multi-checkpoint)

---

## 2. Standard Processing Method

### 2.1 Method Signature

Every stage MUST provide `process_pages()` with:

**Parameters:**
- `start_page: Optional[int]` - First page (default: 1)
- `end_page: Optional[int]` - Last page (default: total_pages)
- `resume: bool` - Resume from checkpoint (default: False)

**Returns:**
- Dict with `total_cost` (float), `statistics` (dict), `pages_processed` (int)

**Why support page ranges?**
- Testing: Run on small subset (pages 1-50)
- Debugging: Re-run specific problematic pages
- Development: Iterate quickly on sample

### 2.2 Processing Flow Principles

**Principle: Checkpoint-Aware Resume**
- If `resume=True`: Call `checkpoint.get_remaining_pages()` to skip completed
- If `resume=False` with checkpoint: Reset checkpoint state
- If no checkpoint: Process all pages in range
- **Always log resume info** (pages skipped, cost saved)

**Principle: Early Exit Optimization**
- Check if `len(page_numbers) == 0` after checkpoint filtering
- Return immediately if nothing to do (don't start executor)
- Log "All pages already completed" for visibility

**Principle: Log Configuration at Start**
- Log: start_page, end_page, total_pages, model, max_workers, resume status
- Essential for reproducing runs and debugging
- Appears in both structured logs (JSON) and console

**Principle: Mark Complete with Metadata**
- After successful processing: `checkpoint.mark_stage_complete()`
- Include: model used, pages_processed, **accumulated** total_cost_usd
- Metadata persists for multi-session tracking

**Principle: Mark Failed on Exception**
- Outer try/except catches stage-level failures
- `checkpoint.mark_stage_failed(error=str(e))` preserves partial progress
- Re-raise exception after marking (don't swallow)
- Allows recovery: completed pages stay completed

**See implementations:**
- `pipeline/correct.py:762-896` (full pattern with 3-agent pipeline)
- `pipeline/fix.py:403-508` (simpler version)
- `pipeline/ocr.py:182-313` (non-LLM stage)

---

## 3. Page-Level Processing

### 3.1 Return Contract

Every `process_single_page()` MUST return a structured dict:

**Required fields:**
- `page: int` - Page number processed
- `status: str` - One of: 'success', 'skipped', 'error', 'not_found'

**Optional fields:**
- `cost: float` - Cost in USD for this page (if LLM calls made)
- `error: str` - Error message (if status == 'error')

**Why structured returns?**
- Parallel executor collects results uniformly
- **Never raise exceptions** from worker functions
- Graceful degradation: one bad page doesn't crash pipeline but still reports errors

### 3.2 Page Processing Principles

**Principle: Save Before Checkpoint**
- Order: `_save_page_output()` → `checkpoint.mark_completed()`
- Checkpoint validates output file exists and is valid
- If save fails, page stays marked incomplete (can retry)

**Principle: Thread-Safe Statistics Updates**
- All `self.stats` updates inside `with self.stats_lock:`
- Prevents race conditions in parallel execution
- Update processed/failed counts and accumulated costs

**Principle: Handle Skip Case**
- Some pages may not need processing (no correctable content, etc.)
- Save skipped page with metadata explaining why
- Return `status: 'skipped'` to avoid re-processing

**Principle: Graceful Error Handling**
- Catch all exceptions in page worker function
- Log error with page context
- Return `status: 'error'` dict (don't raise)
- Continue processing other pages

**See implementations:**
- `pipeline/correct.py:683-760` (3-agent correction)
- `pipeline/ocr.py:407-436` (OCR with image detection)
- `pipeline/fix.py:325-401` (targeted fixes)

---

## 4. Status Tracking

### 4.1 Checkpoint Status

Stages report status through checkpoint system:

**Status values:**
- `not_started` - Stage never run
- `in_progress` - Currently processing
- `completed` - Successfully finished
- `failed` - Stage-level failure occurred

**Access via:** `checkpoint.get_status()` returns full state dict

**Why checkpoint-based status?**
- Persists across process restarts
- External tools can monitor by reading checkpoint files
- Atomic updates (file-based with atomic writes)

### 4.2 Progress Reporting

Stages MUST report progress for monitoring:

**Methods:**
- `logger.start_stage()` - Log configuration at start
- `logger.progress()` - Log every N pages (configurable interval)
- `logger.info()` with statistics - Log completion summary

**Progress data:**
- Current/total pages
- Pages succeeded/failed/skipped
- Accumulated cost
- Estimated completion time (from checkpoint)

**Why frequent progress updates?**
- Long-running stages (15+ minutes for large books)
- User visibility into progress
- External monitoring tools can track
- Helps debug stuck/slow stages

**See implementations:**
- `checkpoint.py:455-476` (progress summary)
- `logger.py:225-248` (progress logging)
- `pipeline/correct.py:855-868` (progress updates in loop)

---

## Summary

A well-structured stage:

1. ✅ Accepts standard initialization parameters
2. ✅ Validates book_dir exists immediately (fail fast)
3. ✅ Creates logger if not provided (standalone + pipeline support)
4. ✅ Loads model from Config with override support
5. ✅ Initializes checkpoint and **accumulates existing costs**
6. ✅ Uses thread-safe statistics
7. ✅ Provides `process_pages()` with checkpoint resume support
8. ✅ Returns structured results from page processing
9. ✅ Handles errors gracefully (returns error status, doesn't crash)
10. ✅ Reports status and progress for monitoring

---

## Next Steps

Continue to [02_checkpointing.md](02_checkpointing.md) to understand how checkpoint resume works in detail.
