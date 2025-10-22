# Checkpoint and Resume Architecture

## Purpose

Enables reliable, resumable batch processing for expensive LLM operations by tracking progress atomically and synchronizing with filesystem state on resume.

## Core Problem

Book processing stages run for hours and cost significant money. Requirements:
- **Interruption tolerance** - Resume from exact point
- **Cost efficiency** - Never reprocess completed pages
- **Data integrity** - Detect and exclude corrupted outputs
- **Concurrent safety** - Multiple workers update progress simultaneously
- **Audit trail** - Complete metrics for every page

## Solution: page_metrics as Source of Truth

**Location:** `infra/storage/checkpoint.py`

The checkpoint file (`.checkpoint`) contains one critical structure:

```json
{
    "stage_name": "corrected",
    "total_pages": 447,
    "status": "in_progress",
    "page_metrics": {
        "1": {"page_num": 1, "cost_usd": 0.032, "tokens_total": 187, ...},
        "2": {"page_num": 2, "cost_usd": 0.028, "tokens_total": 165, ...}
    },
    "metadata": {"total_cost_usd": 1.23, "pages_processed": 100}
}
```

**Invariant:** Page is "complete" if and only if it appears in `page_metrics`.

All other fields derived:
- `completed_pages = len(page_metrics)`
- `progress = completed_pages / total_pages`
- `total_cost_usd = sum(m['cost_usd'] for m in page_metrics.values())`

**Why single source?** Eliminates sync errors between stored counts and actual progress.

## Schema Validation

Every metrics dict validates against `checkpoint_schema`:

```python
# Minimum (BasePageMetrics):
{
    'page_num': int,
    'processing_time_seconds': float,
    'cost_usd': float
}

# Extended for LLM stages (LLMPageMetrics):
{
    # ... BasePageMetrics fields
    'attempts': int,
    'tokens_total': int,
    'model_used': str,
    'queue_time_seconds': float,
    'execution_time_seconds': float,
    'ttft_seconds': Optional[float],
    'usage': Dict[str, Any]
}
```

**Invariant:** Metrics can only be saved if they validate. Catches bugs early.

## Resume Workflow: Three-Phase Synchronization

### Phase 1: Load Checkpoint from Disk

```python
checkpoint = CheckpointManager(checkpoint_file=stage_dir / '.checkpoint')
status = checkpoint.get_status()

if status['status'] == 'completed':
    return status['metadata']  # Skip, already done
```

Initial state may be stale (crash, manual deletion, corruption).

### Phase 2: Scan Existing Outputs and Validate

```python
def get_remaining_pages(self, total_pages, resume=True):
    if resume:
        # Scan actual filesystem (source of truth)
        valid_pages = self.scan_existing_outputs()

        # Update page_metrics to match reality
        for page_num in list(self.page_metrics.keys()):
            if page_num not in valid_pages:
                del self.page_metrics[page_num]  # Remove invalid/missing
```

**scan_existing_outputs() logic:**
1. List all `page_NNNN.json` files
2. Validate each (parse JSON, check schema)
3. Return set of valid page numbers

**Invariant:** Only genuinely valid, complete outputs count as "done."

### Phase 3: Return Remaining Pages

```python
completed = set(self.page_metrics.keys())
remaining = [p for p in range(1, total_pages+1) if p not in completed]
return remaining
```

**Result:** Accurate list of pages needing processing, no duplicates.

## Atomic Write Guarantees

### mark_completed() Implementation

```python
def mark_completed(self, page_num: int, cost_usd: float = 0.0, metrics: dict = None):
    with self._lock:
        # 1. Validate metrics
        if metrics:
            validated = self.checkpoint_schema(**metrics)
            metrics = validated.model_dump()

        # 2. Update in-memory state
        self.page_metrics[page_num] = metrics

        # 3. Persist atomically
        self._save()  # temp file → fsync → rename
```

**Thread safety:** `_lock` ensures only one thread updates at a time.
**Idempotency:** Calling twice with same page_num is safe (last write wins).

### _save() Atomic Pattern

```python
def _save(self):
    temp_path = self.checkpoint_file.with_suffix('.tmp')
    with temp_path.open('w') as f:
        json.dump(self._get_state(), f, indent=2)

    with temp_path.open('r+b') as f:
        os.fsync(f.fileno())  # Force OS write to disk

    temp_path.rename(self.checkpoint_file)  # Atomic
```

**Guarantee:** Crash before rename = old checkpoint intact. After rename = new state. Never corrupted.

## Validation System

### validate_page_output()

Called in two contexts:
1. **On resume** - Validate existing outputs for actual completion
2. **On mark_completed** - Verify output exists and valid before marking

```python
def validate_page_output(self, page_num: int) -> bool:
    page_file = self.output_dir / f"page_{page_num:04d}.json"

    if not page_file.exists():
        return False

    try:
        data = json.loads(page_file.read_text())
        if self.output_schema:
            self.output_schema(**data)  # Raises ValidationError if invalid
        return True
    except (json.JSONDecodeError, ValidationError):
        return False
```

**Invariant:** Only structurally valid outputs count as complete.

## Metrics Collection & Aggregation

### Per-Page Metrics Storage

```python
# In CorrectionStage.run()
metrics = {
    'page_num': page_num,
    'cost_usd': result.cost_usd,
    'processing_time_seconds': result.total_time_seconds,
    'attempts': result.attempts,
    'tokens_total': result.usage['completion_tokens'],
    # ... stage-specific metrics
    'total_corrections': 15,
    'avg_confidence': 0.92
}

checkpoint.mark_completed(page_num, cost_usd=result.cost_usd, metrics=metrics)
```

### get_metrics_summary()

Aggregates statistics across all completed pages:

```python
summary = checkpoint.get_metrics_summary()

# Returns:
{
    'cost_usd': {'min': 0.01, 'max': 0.08, 'sum': 2.34, 'avg': 0.023, 'p50': 0.02, 'p95': 0.06},
    'processing_time_seconds': {'min': 1.2, 'max': 8.5, 'sum': 180.3, ...},
    'tokens_total': {'sum': 18453, 'avg': 187},
    'model_distribution': {'anthropic/claude-sonnet-4': 38, 'gpt-4o': 5},
    'retry_attempts': {'0': 40, '1': 3}
}
```

## Stage Lifecycle Integration

### run() Hook

```python
def run(self, storage, checkpoint, logger):
    # Get pages to process (accounts for resume)
    remaining = checkpoint.get_remaining_pages(total_pages=447, resume=True)

    logger.info(f"Processing {len(remaining)} pages")

    for page_num in remaining:
        data = process_page(page_num)

        # Save data and update checkpoint atomically
        storage.stage(self.name).save_page(page_num, data, metrics=metrics)

    return {"pages_processed": len(remaining)}
```

**Progressive saving:** Checkpoint updated after EACH page, not at end. If interrupted, completed pages don't need re-processing.

### after() Hook

```python
def after(self, storage, checkpoint, logger, stats):
    # Mark stage complete
    checkpoint.mark_stage_complete(metadata=stats)
```

**mark_stage_complete():**
```python
def mark_stage_complete(self, metadata: dict = None):
    with self._lock:
        self.status = 'completed'
        self.completed_at = datetime.now().isoformat()
        if metadata:
            self.metadata.update(metadata)
        self._save()
```

**Effect:** Stage won't re-run on next invocation (runner checks status first).

## Thread Safety & Concurrency

**Lock strategy:** CheckpointManager._lock protects page_metrics dict and file writes.

**Idempotent operations:**
```python
checkpoint.mark_completed(42, metrics={...})
checkpoint.mark_completed(42, metrics={...})  # Safe, last write wins
```

**Copy-on-read:**
```python
def get_status(self):
    with self._lock:
        return {
            'page_metrics': dict(self.page_metrics),  # Copy, not reference
            # ... computed fields
        }
```

Caller can't mutate internal state.

## Cost Tracking & Recovery

### Cost Accumulation

```python
checkpoint.mark_completed(page_num=5, cost_usd=0.032, metrics={...})
checkpoint.mark_completed(page_num=6, cost_usd=0.028, metrics={...})

status = checkpoint.get_status()
print(status['metadata']['total_cost_usd'])  # 0.06
```

**Prevents double-counting:** Each page counted exactly once (idempotency).

### Resume Saves Money

**Scenario:** 447-page book, stage costs $5.00 total
- Process 200 pages (~$2.24)
- Crash/interrupt
- Resume: Only processes remaining 247 pages (~$2.76)
- **Total: $5.00** (not $10.00 if reprocessing all)

## Failure Modes & Recovery

### Scenario 1: Process Killed During Processing

**Recovery:** Re-run command → checkpoint loads → get_remaining_pages() → continues from last checkpoint

**Cost:** Zero duplicate work

### Scenario 2: Checkpoint File Corrupted

**Recovery:** Falls back to empty state → scan_existing_outputs() finds valid pages → rebuilds page_metrics

**Invariant:** Files are source of truth, checkpoint can be rebuilt.

### Scenario 3: Output File Corrupted

**Recovery:** validate_page_output() fails → page removed from page_metrics → re-processed

**Cost:** Re-processing one page (minimal)

## Design Philosophy

### Files Are Facts, Checkpoint Is Progress

**Files:** Immutable, persistent, truth
**Checkpoint:** Mutable, can be stale, rebuilt from files

On resume, always sync checkpoint TO files, never files TO checkpoint.

### Atomic Guarantees Over Speed

Atomic writes cost ~2x vs naive writes, but eliminate corruption entirely. Worth it for hours-long, expensive operations.

### Validate Before Marking Complete

Never trust data without validation. Page only "complete" if:
1. File exists
2. File is valid JSON
3. File validates against output_schema
4. Metrics validate against checkpoint_schema

## Summary

The checkpoint and resume system provides:

1. **Source of truth** - page_metrics dict is single source
2. **Atomic operations** - Temp file → fsync → rename
3. **Resume safety** - Scans filesystem, syncs to reality
4. **Schema validation** - Metrics and outputs validated before marking complete
5. **Thread safety** - Lock-protected updates, idempotent
6. **Cost tracking** - Per-page costs accumulated
7. **Progressive saving** - Each page saved immediately

**Key insight:** Making files the source of truth and checkpoint the progress tracker enables reliable resume (checkpoint rebuilt from files), corruption detection (validate before accepting), and cost efficiency (never reprocess genuinely complete pages).

See also:
- `stage-abstraction.md` - How stages use checkpoints
- `storage-system.md` - Checkpoint integration with storage
- `logging-metrics.md` - Metrics flow to reports
