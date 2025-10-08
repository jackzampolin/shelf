# Next Session: Extraction Tracking & Testing

## Context

We've made significant improvements to the pipeline:
- ✅ Complete model configuration cleanup (no hardcoded models)
- ✅ CLI refactoring (split `structure` → `extract` + `assemble`)
- ✅ JSON retry logic in all extraction agents
- ✅ Extract checkpoint now created at start (shows "in progress")

## Current Issue

The extraction stage has **poor progress visibility** during execution:

**Problem:**
- Batch files are only saved AFTER all processing + reconciliation completes
- Other stages (OCR, correction, fix) save incrementally
- Status command can't show progress until extraction fully finishes
- Only shows "Extract: In progress" with no percentage

**Impact:**
- User can't see how far along extraction is (could be 10% or 90%)
- Long-running extractions (10-20 min) have no progress feedback
- Inconsistent with other pipeline stages

## Goals for Next Session

### 1. Improve Extraction Progress Tracking

**Option A: Incremental Batch Saving** (Recommended)
- Save each batch file immediately after it's processed
- Similar to how correction stage works
- Allows status to count `batch_*.json` files for progress
- Trade-off: Need to update files during reconciliation phase

**Option B: Enhanced Checkpoint Updates**
- Update extract checkpoint with progress during processing
- Store `total_batches` and `completed_batches` in metadata
- ParallelProcessor already reports progress every 5 batches
- Hook into that callback to update checkpoint

**Recommendation:** Start with Option B (simpler, less risky)

### 2. Clean Up and Re-test accidental-president

The current extraction had mixed results:
- 35/64 batches succeeded (many failures even with retry)
- Assembly completed but only 191/447 pages covered
- Need to understand why so many batches failed

**Tasks:**
```bash
# Clean up failed extraction
rm -rf ~/Documents/book_scans/accidental-president/structured/
rm ~/Documents/book_scans/accidental-president/checkpoints/extract.json
rm ~/Documents/book_scans/accidental-president/checkpoints/assemble.json

# Re-run extraction with improved tracking
uv run python ar.py extract accidental-president --resume

# Monitor progress (should now show percentage)
uv run python ar.py status accidental-president --watch
```

### 3. Investigate Batch Failures

Many batches failed even with JSON retry logic:
- Batch 21: "Expecting value: line 160 column 15"
- Batch 40: "Response ended prematurely"
- Pattern: JSON parsing still failing after 2 retries

**Questions to answer:**
- Are failures due to malformed JSON or network issues?
- Should we increase retry count (2 → 3)?
- Do we need better error handling for specific error types?
- Should we log the full response on final retry failure?

## Implementation Steps

### Step 1: Add Progress Tracking (30 min)

**File:** `pipeline/structure/extractor.py`

```python
# In ExtractionOrchestrator.__init__:
self.checkpoint = checkpoint  # Accept checkpoint from BookStructurer

# In extract_sliding_window, after progress logging:
if self.checkpoint:
    self.checkpoint._state['metadata']['total_batches'] = len(batches)
    self.checkpoint._state['metadata']['completed_batches'] = completed_count
    self.checkpoint._save_checkpoint()
```

**File:** `pipeline/structure/__init__.py`

```python
# Pass checkpoint to extractor:
extractor = ExtractionOrchestrator(
    scan_id=self.scan_id,
    storage_root=self.storage_root,
    logger=self.logger,
    checkpoint=self.checkpoint_extract  # Add this
)
```

**File:** `tools/monitor.py`

```python
# In get_stage_status for extract:
if stage == 'extract':
    total_batches = metadata.get('total_batches', 0)
    completed_batches = metadata.get('completed_batches', 0)
    if total_batches > 0:
        progress_current = completed_batches
        progress_total = total_batches
```

### Step 2: Clean and Re-run (15 min)

```bash
# Clean up
rm -rf ~/Documents/book_scans/accidental-president/structured/
rm ~/Documents/book_scans/accidental-president/checkpoints/extract.json
rm ~/Documents/book_scans/accidental-president/checkpoints/assemble.json

# Verify cleanup
uv run python ar.py status accidental-president

# Re-run with new tracking
uv run python ar.py extract accidental-president
```

### Step 3: Monitor and Validate (ongoing)

Watch extraction in real-time:
```bash
# In one terminal: watch status
watch -n 5 'uv run python ar.py status accidental-president'

# In another: watch logs
tail -f ~/Documents/book_scans/accidental-president/logs/extraction_*.jsonl | grep -E "Progress|failed"
```

Expected outcome:
- Status shows "Extract: X/64 (Y%)"
- Progress updates every 5 batches
- Can estimate time remaining

## Success Criteria

- [ ] Status command shows batch-level progress (e.g., "Extract: 45/64 (70%)")
- [ ] Progress updates at least every 5 batches during extraction
- [ ] accidental-president extracts successfully with <10% batch failure rate
- [ ] If failures occur, logs show clear retry attempts
- [ ] Full extraction completes and assembles at least 400/447 pages

## Notes

- Extract checkpoint now created at start (commit 49b6c27)
- JSON retry logic integrated in all 3 agents (commit 5cb52c3)
- Status already has infrastructure for tracking progress - just needs data
- Consider: Should we fail the stage if >25% of batches fail?

## Related Issues

This relates to findings in `docs/FIRST_BOOK_PROCESSING_PLAN.md`:
- Expected 5-10 min extraction time for 400 pages
- Expected ~$1-3 cost
- Expected <5% failure rate

Current extraction took ~14 min, cost $0.42, had 45% failure rate. Need to understand why.
