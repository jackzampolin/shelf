# Checkpoint Two-Stage Tracking Audit

## Critical Bug Found

### Problem: Stage 2 Metrics Are Lost

**Location:** `infra/storage/checkpoint.py:378-379`

```python
def mark_completed(self, page_num: int, cost_usd: float = 0.0, metrics: Optional[Dict[str, Any]] = None):
    with self._lock:
        page_key = str(page_num)
        if page_key in self._state.get('page_metrics', {}):
            return  # ← BUG: Early return loses Stage 2 metrics!
```

**What happens:**
1. Stage 1 completes → `checkpoint.mark_completed(page_num=1, metrics={'stage': 'stage1', ...})`
2. Stage 2 completes → `checkpoint.mark_completed(page_num=1, metrics={...stage2 metrics...})`
3. Checkpoint sees page 1 exists → returns early
4. **Stage 2 metrics never saved!**

**Evidence from actual checkpoint:**
```json
{
  "1": {"stage": "stage1"},
  "2": {"stage": "stage1"},
  ...
}
```

No Stage 2 cost, tokens, or block classification metrics!

**Impact:**
- All Stage 2 costs lost
- status.py shows `stage2_cost_usd: 0.0` (always)
- Can't track actual total cost
- Metrics are incomplete

## Current Call Flow

### Stage 1 Handler (handlers.py:24-28)
```python
checkpoint.mark_completed(
    page_num=page_num,
    cost_usd=result.cost_usd or 0.0,
    metrics={'stage': 'stage1'},  # Minimal metrics
)
```

### Stage 2 Handler (handlers.py:103-110)
```python
stage_storage.save_labeled_page(
    storage=storage,
    page_num=page_num,
    data=validated.model_dump(),
    schema=output_schema,
    cost_usd=result.cost_usd or 0.0,
    metrics=metrics.model_dump(),  # Full metrics from LabelPagesPageMetrics
)
```

### save_labeled_page → save_page (book_storage.py:250)
```python
checkpoint.mark_completed(page_num, cost_usd=cost_usd, metrics=metrics)
```

**Both stages call `mark_completed()` for same page_num!**

## Solution Options

### Option 1: Accumulate Metrics (RECOMMENDED)

Modify `checkpoint.mark_completed()` to merge metrics when called multiple times:

```python
def mark_completed(self, page_num: int, cost_usd: float = 0.0, metrics: Optional[Dict[str, Any]] = None):
    with self._lock:
        page_key = str(page_num)

        # Initialize page_metrics if needed
        if 'page_metrics' not in self._state:
            self._state['page_metrics'] = {}

        # Check if page already has metrics (multi-stage case)
        if page_key in self._state['page_metrics']:
            existing = self._state['page_metrics'][page_key]

            # Accumulate costs
            existing_cost = existing.get('cost_usd', 0.0)
            new_cost = metrics.get('cost_usd', cost_usd) if metrics else cost_usd

            # Merge metrics
            if metrics:
                # Create stage-specific keys for multi-stage tracking
                stage = metrics.get('stage')
                if stage:
                    # Stage 1: Store as stage1_*
                    for key, value in metrics.items():
                        if key != 'stage':
                            existing[f'{stage}_{key}'] = value
                else:
                    # Stage 2: Store as-is (final metrics)
                    existing.update(metrics)

                # Update total cost
                existing['cost_usd'] = existing_cost + new_cost

            self._save_checkpoint()
            return

        # First call for this page - store as usual
        if metrics:
            self._state['page_metrics'][page_key] = metrics
        else:
            self._state['page_metrics'][page_key] = {
                "page_num": page_num,
                "cost_usd": cost_usd
            }

        self._save_checkpoint()
```

**Benefits:**
- Backward compatible (single-stage still works)
- Stage 1 and Stage 2 costs accumulated
- Stage-specific metrics preserved (stage1_*, final metrics)
- status.py can extract both stages

**Result:**
```json
{
  "1": {
    "stage1_cost_usd": 0.0012,
    "stage1_tokens_input": 234,
    "stage1_tokens_output": 89,
    "cost_usd": 0.0039,  // stage1 + stage2
    "tokens_input": 678,
    "tokens_output": 234,
    "total_blocks_classified": 12,
    ...
  }
}
```

### Option 2: Separate Keys

Use different keys: `"1_stage1"`, `"1_stage2"`

**Problems:**
- Breaking change to checkpoint format
- status.py needs to parse keys
- Complicates page completion logic
- Not backward compatible

### Option 3: Nested Structure

```json
{
  "1": {
    "stage1": {...},
    "stage2": {...}
  }
}
```

**Problems:**
- Breaking change to checkpoint format
- status.py needs rewrite
- Complicates existing code
- Not backward compatible

## Recommended Fix

**Option 1: Accumulate metrics** is the best approach:

1. **Backward compatible**: Single-stage works as before
2. **Clean**: Stage 1 metrics prefixed with `stage1_`, Stage 2 as-is
3. **Accurate**: Costs accumulated, no data loss
4. **Minimal changes**: Only checkpoint.py needs update

## Testing After Fix

1. **Fresh run**: Both stages → checkpoint has stage1_* and final metrics
2. **Cost tracking**: stage1_cost + stage2_cost = total_cost
3. **Token tracking**: stage1_tokens and stage2_tokens both present
4. **status.py**: Can extract stage-specific metrics correctly

## Related Files

- `infra/storage/checkpoint.py:365` - mark_completed() needs fix
- `pipeline/label_pages/tools/handlers.py` - Both handlers call mark_completed
- `pipeline/label_pages/status.py` - Extracts stage-specific metrics
