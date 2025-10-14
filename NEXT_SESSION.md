# Next Session: Run Correction Stage on All Books

## Context

Just completed unified terminal output improvements and OCR hang fix:
- ✅ Created `infra/progress.py` - reusable progress bar utility
- ✅ Updated `tools/add.py` - clean progress bars for PDF extraction
- ✅ Updated `pipeline/1_ocr/__init__.py` - clean progress bars for OCR
- ✅ Updated `pipeline/2_correction/__init__.py` - clean progress bars for correction
- ✅ Created `docs/standards/10_terminal_output.md` - comprehensive formatting standards
- ✅ Fixed OCR hang issue with worker adjustment and timeout protection

## Current Status

**OCR Stage:**
- ✅ **FIXED**: OCR hang issue resolved
  - Implemented worker adjustment: caps at min(max_workers, task_count, 8)
  - Added 300s timeout to future.result()
  - Tested on china-lobby book - successfully processed page 6
  - Commits: 3bb9924 (OCR fix), 1762db4 (correction output)

**Correction Stage:**
- Ready to test with unified output formatting
- Uses `ProgressBar` with cost tracking in suffix: `"23 ok, $1.45, 2 failed"`
- Clean stage boundaries: `🔧 Correction Stage (book-title)` → `✅ Correction complete`

## Expected Correction Stage Output

```
🔧 Correction Stage (hap-arnold)
   Pages:     340
   Workers:   30
   Model:     google/gemini-2.5-flash-lite-preview-09-2025

   Correcting 340 pages...
   [████████████████████████████████░░░░░░░░] 82% (279/340) - 3.2 pages/sec - ETA 19s - 279 ok, $2.45, 0 failed
   ✓ 279/340 pages corrected

✅ Correction complete: 340/340 pages
   Total cost: $2.98
   Avg per page: $0.009
```

## Next Steps

### 1. Check OCR Status on All Books

First, verify all books have completed OCR:

```bash
uv run python ar.py library list
```

Look for books with `ocr_complete: false` and complete any remaining OCR runs.

### 2. Run Correction Stage on All Books

**Test on one book first:**
```bash
# Pick a book to test correction stage
uv run python ar.py process correction <scan-id> --resume
```

**Verify output format:**
- Clean stage entry: 🔧 Correction Stage (book-title)
- Progress bar with cost tracking: "279 ok, $2.45, 0 failed"
- Clean stage exit: ✅ Correction complete

**Once verified, run on all books:**
```bash
# Option A: One at a time (manual)
uv run python ar.py process correction hap-arnold --resume
uv run python ar.py process correction china-lobby --resume
# ... etc

# Option B: Batch script (create helper)
# for scan_id in $(cat scan_ids.txt); do
#     uv run python ar.py process correction $scan_id --resume
# done
```

## Files Modified This Session

1. **UPDATED:** `pipeline/1_ocr/__init__.py` - Fixed hang issue (lines 393-436)
   - Worker adjustment: min(max_workers, task_count, 8)
   - Timeout protection: 300s per page
   - Unified output formatting
   - Commit: 3bb9924

2. **UPDATED:** `pipeline/2_correction/__init__.py` - Unified output (lines 28, 168-297)
   - Added ProgressBar with cost tracking
   - Clean stage entry/exit
   - Removed logger stdout spam
   - Commit: 1762db4

**Previously modified (earlier in session):**
3. **NEW:** `infra/progress.py` - Progress bar utility
4. **UPDATED:** `tools/add.py` - Clean output formatting
5. **NEW:** `docs/standards/10_terminal_output.md` - Output standards

## Testing Checklist

After running correction stage on test book:
- [ ] Verify single-line progress bar updates smoothly
- [ ] Verify cost tracking shows in suffix
- [ ] Verify stage entry/exit formatting matches standards
- [ ] Verify errors print on new lines without breaking progress
- [ ] Verify no logger stdout spam during processing
- [ ] Check log files to ensure errors are still logged to file

## Architecture Notes

**Progress Bar Pattern:**
```python
from infra.progress import ProgressBar

# Initialize
progress = ProgressBar(
    total=total_items,
    prefix="   ",  # 3-space indent
    width=40,      # Standard width
    unit="pages"   # or "items", "files", etc.
)

# Update in loop
for item in items:
    # ... process item ...
    progress.update(current, suffix=f"{completed} ok")

# Finish
progress.finish(f"   ✓ {completed}/{total} items processed")
```

**Logger Pattern:**
```python
# Visual progress: ProgressBar for terminal output
progress.update(current, suffix=status)

# File logging: logger for debugging (no stdout spam)
if error:
    logger.error("Operation failed", page=page_num, error=error_msg)
```

## Cost Tracking

Correction stage costs ~$0.008-0.012 per page with `google/gemini-2.5-flash-lite-preview-09-2025`.

**Estimated costs for remaining books:**
- Assuming ~300 pages per book average
- 9 books remaining after OCR
- ~2700 pages × $0.01 = ~$27 total for correction stage

**Budget check before running:**
```bash
# Check page counts
uv run python ar.py library list

# Calculate estimated cost
# (sum of pages) × $0.01 = estimated cost
```

## OCR Hang Fix Details

**Problem:**
ProcessPoolExecutor worker spawn failures on macOS (spawn mode) caused indefinite hangs when resuming OCR with 1-2 pages remaining.

**Solution Implemented:**
1. **Worker adjustment** (line 395):
   ```python
   effective_workers = min(self.max_workers, len(tasks), 8)
   ```
   - Caps workers at task count (1 task = 1 worker)
   - Max 8 workers for small jobs (reduces spawn overhead)
   - Prevents wasted worker spawns that may fail

2. **Timeout protection** (line 411):
   ```python
   success, page_number, error_msg, page_data = future.result(timeout=300)
   ```
   - 5 minutes per page (generous for Tesseract OCR)
   - Converts silent hangs to TimeoutError
   - Logged and counted as failed page (can retry)

**Testing:**
- Tested on china-lobby book (previously hung on page 6)
- Worker adjustment: 16 → 1 worker for 1 task
- Successfully completed in ~2 minutes
- No hang, clean output

## References

- Terminal Output Standards: `docs/standards/10_terminal_output.md`
- Progress Bar Utility: `infra/progress.py`
- Current branch: `refactor/pipeline-redesign`
- Recent commits: 3bb9924 (OCR fix), 1762db4 (correction output)

---

**Start here next session:**
1. Check OCR status on all books
2. Test correction stage on one book (verify output formatting)
3. Run correction stage on all books once verified
