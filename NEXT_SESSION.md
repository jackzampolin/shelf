# Next Session: Terminal Output Improvements

## Context

Just completed major performance optimizations:
- ✅ Dual-DPI strategy (600 DPI for OCR, 300 DPI for vision)
- ✅ Parallel PDF extraction (uses all CPU cores)
- ✅ Parallel OCR processing (ProcessPoolExecutor, auto-detects cores)
- ✅ Full CPU saturation achieved (~100% utilization)

**Current Issue:** Terminal output is too verbose/spammy during add and OCR stages.

## Goal

Improve terminal UX for `ar library add` and `ar process ocr`:
- Use `\r` (carriage return) for in-place updates instead of spamming new lines
- Add nice progress bars for both stages
- Clean, minimal output that's easy to follow

## Current Behavior

### PDF Extraction (tools/add.py)
```
   Extracting pages from 2 PDF(s) at 600 DPI...
     Processing 447 pages in parallel...
     Progress: 10/447 pages (10 ok, 0 failed)
     Progress: 20/447 pages (20 ok, 0 failed)
     Progress: 30/447 pages (30 ok, 0 failed)
     ...
     [lots of spam]
```

**Issues:**
- Updates every 10 pages (creates ~45 lines for 447 pages)
- No visual progress bar
- Hard to see at-a-glance progress

### OCR Stage (pipeline/1_ocr/__init__.py)
```
📄 Processing 447 pages with Tesseract OCR...
[progress updates via logger]
```

**Issues:**
- OCR has progress via logger but could be nicer
- Inconsistent with extraction output

## Desired Behavior

### PDF Extraction
```
   Extracting 447 pages at 600 DPI (using 16 cores)...
   [████████████████████████████░░░░░░░░] 75% (335/447) - 2.1 pages/sec - ETA 53s
```

### OCR Processing
```
📄 OCR Processing (Tesseract)...
   [█████████████████████████████░░░░░░] 80% (356/447) - 1.8 pages/sec - ETA 51s
```

**Features:**
- Single line that updates in place with `\r`
- Visual progress bar (████████░░░░)
- Percentage, count (current/total)
- Processing rate (pages/sec)
- Estimated time remaining (ETA)
- Only new line on completion or error

## Implementation Plan

### 1. Create Unified Progress Bar Utility

**File:** `infra/progress.py`

```python
class ProgressBar:
    """In-place terminal progress bar with \r updates."""

    def __init__(self, total: int, prefix: str = "", width: int = 40):
        self.total = total
        self.prefix = prefix
        self.width = width
        self.start_time = time.time()

    def update(self, current: int, suffix: str = ""):
        """Update progress bar in place."""
        # Calculate metrics
        percent = (current / self.total) * 100
        filled = int(self.width * current // self.total)
        bar = '█' * filled + '░' * (self.width - filled)

        # Calculate rate and ETA
        elapsed = time.time() - self.start_time
        rate = current / elapsed if elapsed > 0 else 0
        eta = (self.total - current) / rate if rate > 0 else 0

        # Format output
        output = f"\r{self.prefix}[{bar}] {percent:.0f}% ({current}/{self.total})"
        if rate > 0:
            output += f" - {rate:.1f} pages/sec"
        if eta > 0 and eta < 3600:  # Only show ETA if < 1 hour
            output += f" - ETA {format_seconds(eta)}"
        if suffix:
            output += f" - {suffix}"

        # Print with \r (carriage return) to overwrite
        print(output, end='', flush=True)

    def finish(self, message: str = ""):
        """Print final newline and completion message."""
        print()  # New line after progress bar
        if message:
            print(message)
```

### 2. Update PDF Extraction

**File:** `tools/add.py`

Update the progress tracking (lines 186-215):

```python
from infra.progress import ProgressBar

# After task submission
progress = ProgressBar(
    total=total_pages,
    prefix="   Extracting pages: ",
    width=40
)

for future in as_completed(future_to_task):
    # ... existing logic ...

    # Update progress bar
    current = completed + failed
    suffix = f"{completed} ok" + (f", {failed} failed" if failed > 0 else "")
    progress.update(current, suffix=suffix)

# Finish
progress.finish(f"   ✓ Extracted {completed}/{total_pages} pages → source/")
```

### 3. Update OCR Stage

**File:** `pipeline/1_ocr/__init__.py`

Update progress tracking (lines 373-420):

```python
from infra.progress import ProgressBar

print(f"📄 OCR Processing (Tesseract, {self.max_workers} workers)...")

progress = ProgressBar(
    total=len(tasks),
    prefix="   ",
    width=40
)

for future in as_completed(future_to_task):
    # ... existing logic ...

    # Update progress bar
    current = completed + errors
    suffix = f"{completed} ok" + (f", {errors} failed" if errors > 0 else "")
    progress.update(current, suffix=suffix)

# Finish
progress.finish(f"   ✓ {completed}/{total_pages} pages processed → {ocr_dir}")
```

### 4. Suppress Logger Progress (Optional)

Since we're using the visual progress bar, we might want to suppress the logger progress updates during processing:

**Option A:** Only log to file, not stdout during processing
**Option B:** Keep logger for errors only
**Option C:** Keep logger as-is (for debugging)

**Recommendation:** Start with Option B - only log errors to stdout during processing.

## Testing Checklist

After implementation:
- [ ] Test `ar library add <pdf>` - verify single-line progress bar
- [ ] Test `ar process ocr <scan-id>` - verify single-line progress bar
- [ ] Test with small book (10 pages) - verify no flicker/spam
- [ ] Test with large book (400+ pages) - verify smooth updates
- [ ] Test with failures - verify error messages don't break progress bar
- [ ] Test terminal width handling - verify bar adjusts or truncates gracefully
- [ ] Verify ETA accuracy (should stabilize after ~30 pages)

## Files to Modify

1. **NEW:** `infra/progress.py` - Create progress bar utility
2. **UPDATE:** `tools/add.py` - Use progress bar for PDF extraction (lines 186-215)
3. **UPDATE:** `pipeline/1_ocr/__init__.py` - Use progress bar for OCR (lines 373-420)
4. **OPTIONAL:** `infra/logger.py` - Suppress progress logs to stdout during processing

## Nice-to-Haves (Future)

- Color support (green for success, red for errors)
- Spinner for indeterminate operations
- Multi-line progress for concurrent stages
- Progress persistence (resume shows where it left off)

## References

- Current commits: 04ece28, 81489fb, 8b45d15, 42d7981, b9c830e, 08a9588
- Branch: `refactor/pipeline-redesign`
- Related: Issue #56 (Pipeline Refactor)

---

**Start here next session:** Create `infra/progress.py` with the ProgressBar class, then update add.py to use it.
