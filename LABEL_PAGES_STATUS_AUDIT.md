# Label-Pages Status Audit

## Current Two-Stage Architecture

```
Stage 1: Structural Analysis (3-image context)
├── Input: source/page_XXXX.png (prev, current, next)
├── Output: label-pages/stage1/page_XXXX.json
└── Purpose: Extract page numbers, regions, structural boundaries

Stage 2: Block Classification (1-image + Stage 1 context)
├── Input: source/page_XXXX.png + stage1 results + OCR blocks
├── Output: label-pages/page_XXXX.json (FINAL)
└── Purpose: Classify blocks using Stage 1 guidance
```

## Issues Found in status.py

### 1. Status Enum Doesn't Distinguish Stages (Lines 11-15)

**Current:**
```python
class LabelPagesStatus(str, Enum):
    NOT_STARTED = "not_started"
    LABELING = "labeling"              # ← Generic, doesn't distinguish stages
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
```

**Problem:** User sees "labeling" but doesn't know if it's Stage 1 or Stage 2

**Recommendation:**
```python
class LabelPagesStatus(str, Enum):
    NOT_STARTED = "not_started"
    LABELING_STAGE1 = "labeling_stage1"  # Structural analysis (3-image)
    LABELING_STAGE2 = "labeling_stage2"  # Block classification (1-image)
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"
```

### 2. get_progress() Only Checks Final Output (Line 36)

**Current:**
```python
completed_pages = self.storage.list_completed_pages(storage)
remaining_pages = [
    p for p in range(1, total_pages + 1)
    if p not in completed_pages
]
```

**Problem:**
- Only checks `page_XXXX.json` (Stage 2 final output)
- Doesn't track Stage 1 progress separately
- User can't see "Stage 1: 447/447, Stage 2: 150/447"

**Recommendation:**
```python
# Check both stages separately
stage1_completed = self.storage.list_stage1_completed_pages(storage)
stage2_completed = self.storage.list_completed_pages(storage)

stage1_remaining = [p for p in range(1, total_pages + 1) if p not in stage1_completed]
stage2_remaining = [p for p in range(1, total_pages + 1) if p not in stage2_completed]
```

### 3. Status Logic Doesn't Account for Two Stages (Lines 44-51)

**Current:**
```python
if len(remaining_pages) == total_pages:
    status = LabelPagesStatus.NOT_STARTED.value
elif len(remaining_pages) > 0:
    status = LabelPagesStatus.LABELING.value  # ← Which stage?
elif not report_exists:
    status = LabelPagesStatus.GENERATING_REPORT.value
else:
    status = LabelPagesStatus.COMPLETED.value
```

**Problem:** Can't tell if we're in Stage 1 or Stage 2

**Recommendation:**
```python
if len(stage1_remaining) == total_pages:
    # Neither stage has started
    status = LabelPagesStatus.NOT_STARTED.value
elif len(stage1_remaining) > 0:
    # Stage 1 still in progress
    status = LabelPagesStatus.LABELING_STAGE1.value
elif len(stage2_remaining) > 0:
    # Stage 1 complete, Stage 2 in progress
    status = LabelPagesStatus.LABELING_STAGE2.value
elif not report_exists:
    # Both stages complete, generating report
    status = LabelPagesStatus.GENERATING_REPORT.value
else:
    # Everything complete
    status = LabelPagesStatus.COMPLETED.value
```

### 4. Metrics Don't Separate Stage 1 and Stage 2 Costs (Lines 56-86)

**Current:**
```python
for metrics in page_metrics.values():
    total_cost += metrics.get('cost_usd', 0.0)
    # All costs aggregated together
```

**Problem:** Can't see Stage 1 cost vs Stage 2 cost separately

**Recommendation:**
```python
stage1_cost = 0.0
stage2_cost = 0.0

for page_num, metrics in page_metrics.items():
    stage = metrics.get('stage')  # 'stage1' or 'stage2'
    cost = metrics.get('cost_usd', 0.0)

    if stage == 'stage1':
        stage1_cost += cost
    else:
        stage2_cost += cost

total_cost = stage1_cost + stage2_cost
```

### 5. Return Value Doesn't Show Stage-Specific Progress (Lines 90-106)

**Current:**
```python
return {
    "status": status,
    "total_pages": total_pages,
    "remaining_pages": remaining_pages,  # ← Which stage?
    ...
}
```

**Problem:** User can't see Stage 1 vs Stage 2 progress

**Recommendation:**
```python
return {
    "status": status,
    "total_pages": total_pages,
    "stage1_remaining": stage1_remaining,
    "stage2_remaining": stage2_remaining,
    "remaining_pages": stage2_remaining,  # Keep for backward compat
    "metrics": {
        "stage1_cost_usd": stage1_cost,
        "stage2_cost_usd": stage2_cost,
        "total_cost_usd": total_cost,
        ...
    },
    ...
}
```

## Comparison with Other Stages

### OCR Stage (reference implementation)
- Single-stage: Uses simple PROCESSING status
- Ground truth: Checks output files on disk
- Clear status progression: NOT_STARTED → PROCESSING → COMPLETED

### Paragraph-Correct Stage
- Single-stage: Uses CORRECTING status
- Similar pattern to OCR

### Label-Pages (current - NEEDS FIX)
- Two-stage: Should use LABELING_STAGE1 → LABELING_STAGE2
- Currently: Generic LABELING doesn't distinguish

## File/Folder Verification

### Correct Folder Structure
```
label-pages/
├── stage1/              # Stage 1 intermediate results
│   └── page_XXXX.json   # Structural analysis
├── logs/                # LLM call logs
│   ├── stage1/          # Stage 1 logs
│   └── stage2/          # Stage 2 logs
├── page_XXXX.json       # Final output (Stage 1 + Stage 2 merged)
├── report.csv           # Summary report
└── .checkpoint          # Progress tracking
```

### Current Storage Methods (storage.py)

✅ **Correct:**
- `list_completed_pages()` - Checks `label-pages/page_XXXX.json` (final output)
- `list_stage1_completed_pages()` - Checks `label-pages/stage1/page_XXXX.json`
- `get_stage1_dir()` - Returns `label-pages/stage1/`

❌ **Missing in status.py:**
- Status doesn't use `list_stage1_completed_pages()` to track Stage 1 progress

## Summary of Required Changes

### status.py
1. **Update enum**: Add LABELING_STAGE1 and LABELING_STAGE2
2. **Track both stages**: Check stage1 and stage2 remaining separately
3. **Fix status logic**: Distinguish between Stage 1 and Stage 2 progress
4. **Separate metrics**: Show Stage 1 vs Stage 2 costs
5. **Update return value**: Include stage-specific progress

### Backward Compatibility
- Keep `remaining_pages` field (= stage2_remaining) for existing tools
- Keep `total_cost_usd` (= stage1_cost + stage2_cost)
- Add new fields without breaking existing consumers

## Testing Checklist

After fixing status.py:

- [ ] NOT_STARTED: Fresh book, no files → status = "not_started"
- [ ] LABELING_STAGE1: stage1/ has some files → status = "labeling_stage1"
- [ ] LABELING_STAGE2: stage1/ complete, page_XXXX.json partial → status = "labeling_stage2"
- [ ] GENERATING_REPORT: All pages complete, no report.csv → status = "generating_report"
- [ ] COMPLETED: All pages + report.csv exist → status = "completed"
- [ ] Metrics: Stage 1 and Stage 2 costs shown separately
- [ ] Progress: Can see "Stage 1: 447/447, Stage 2: 150/447"
