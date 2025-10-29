# OCR Checkpoint Refactor Plan

## Goal
Consolidate OCR sub-stage tracking into main checkpoint instead of 4 separate checkpoint files.

## Current State (Broken)
- Main `ocr/.checkpoint`: unused, empty (total_pages=0)
- PSM checkpoints: `ocr/psm3/.checkpoint`, `ocr/psm4/.checkpoint`, `ocr/psm6/.checkpoint`
- Vision checkpoint: `ocr/psm_selection/.checkpoint`
- **Problem**: Main checkpoint not synced, sweep can't detect completion

## Target Schema

**Main checkpoint** (`ocr/.checkpoint`):
```json
{
  "total_pages": 616,
  "status": "in_progress",
  "page_metrics": {
    "1": {
      "psm3": true,
      "psm4": true,
      "psm6": true,
      "vision_psm": 3
    }
  },
  "metadata": {
    "psm_modes": [3, 4, 6],
    "total_cost_usd": 0.0
  }
}
```

## Code Changes Needed

### 1. Initialize main checkpoint (`run()` start)
```python
# Set total_pages in main checkpoint
checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)
```

### 2. Replace PSM checkpoint creation (lines 141-168)
**Remove:**
```python
psm_checkpoint = CheckpointManager(...)
pages = psm_checkpoint.get_remaining_pages(...)
```

**Replace with:**
```python
pages = self._get_remaining_pages_for_psm(checkpoint, total_pages, psm)
```

### 3. Update mark_completed (line 229-234)
**Remove:**
```python
psm_checkpoint.mark_completed(page_num, ...)
```

**Replace with:**
```python
# Get existing metrics for this page (preserve other PSMs)
status = checkpoint.get_status()
existing_metrics = status.get('page_metrics', {}).get(str(page_num), {})

# Update with this PSM's completion
existing_metrics[f'psm{psm}'] = True

# Mark in main checkpoint
checkpoint.mark_completed(
    page_num=page_num,
    cost_usd=0.0,
    metrics=existing_metrics
)
```

### 4. Update vision selection (line ~862)
**Change vision checkpoint to use main checkpoint:**
```python
# Don't create separate vision checkpoint
# Use main checkpoint and track vision_psm field
```

### 5. Update `after()` completion check (lines 257-294)
**Remove** separate checkpoint checks for PSMs/vision.

**Replace with:**
```python
# Check main checkpoint page_metrics
status = checkpoint.get_status()
page_metrics = status.get('page_metrics', {})
total_pages = status.get('total_pages', 0)

all_complete = True
for page_num in range(1, total_pages + 1):
    metrics = page_metrics.get(str(page_num), {})

    # Check all PSMs complete
    for psm in self.psm_modes:
        if not metrics.get(f'psm{psm}', False):
            all_complete = False
            break

    # Check vision selection complete
    if metrics.get('vision_psm') is None:
        all_complete = False
        break

if all_complete:
    checkpoint.mark_stage_complete()
```

## Sync Script

**Purpose**: Rebuild main checkpoint from existing PSM directory files.

**Algorithm**:
1. Scan `ocr/psm{N}/page_*.json` files
2. For each file found, set `page_metrics[page]['psm{N}'] = true`
3. Load `ocr/psm_selection.json` and set `vision_psm` values
4. Set total_pages from metadata
5. Calculate status based on completion

## Migration Path

1. ✅ Create helper method `_get_remaining_pages_for_psm()`
2. ⏳ Refactor `run()` PSM loop to use main checkpoint
3. ⏳ Refactor vision selection to use main checkpoint
4. ⏳ Update `after()` completion logic
5. ⏳ Write sync script
6. ⏳ Run sync script on all 19 books
7. ⏳ Test on sample book

## Files to Modify

- `pipeline/ocr/__init__.py` (~300 lines, complex)
- Create: `tools/sync_ocr_main_checkpoint.py`

## Estimated Effort

- Code changes: 1-2 hours (careful refactoring)
- Testing: 30 min (one book, ~20 min OCR time)
- Sync script: 30 min

**Total**: 2-3 hours
