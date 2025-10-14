# Terminal Output Standards

## Overview

Consistent, clean terminal output makes the pipeline easy to follow and understand. This document defines formatting conventions for all pipeline stages and tools.

## Core Principles

1. **Visual Hierarchy**: Use consistent indentation and symbols
2. **Progress Visibility**: Single-line progress bars that update in place
3. **Error Clarity**: Errors print on new lines without breaking progress
4. **Stage Boundaries**: Clear entry/exit markers for each stage
5. **Minimal Noise**: No redundant messages or logger spam

## Formatting Standards

### Stage Entry

```
📚 Stage Name (context)
```

**Examples:**
- `📚 Book Ingestion (hap-arnold)`
- `📄 OCR Processing (hap-arnold)`
- `🔧 Correction Stage (hap-arnold)`

### Operation with Progress

```
   Operation description...
   [progress bar] percentage (current/total) - rate - ETA - status
   ✓ Completion message
```

**Examples:**
```
   Extracting 340 pages at 600 DPI...
   [████████████████░░░░] 80% (272/340) - 23.1 pages/sec - ETA 3s - 272 ok
   ✓ Extracted 340/340 pages
```

### Stage Exit

```
✅ Stage complete (summary)
```

**Examples:**
- `✅ Book registered: hap-arnold`
- `✅ OCR complete: 340/340 pages processed`

### Errors

Errors print on new lines to avoid breaking progress bars:

```
   [progress bar updates...]

   ⚠️  Page 42 failed: Invalid image format
   [progress bar continues...]
```

**After completion, summarize errors:**
```
   ✓ 338/340 pages processed
   ⚠️  2 pages failed
```

### Information Messages

Use indentation for context:

```
   Title:     Hap Arnold
   Author:    Unknown
   Pages:     340
```

## Indentation Guide

- **Stage markers** (📚 ✅): No indentation
- **Operation descriptions**: 3 spaces (`   `)
- **Progress bars**: 3 spaces (`   `)
- **Info/details**: 6 spaces (`      `)
- **Nested details**: 9 spaces (`         `)

## Symbol Reference

- `📚` - Stage entry (ingestion, processing)
- `📄` - OCR/document operations
- `🔧` - Correction/fixing operations
- `✅` - Success/completion
- `✓` - Sub-operation success
- `⚠️` - Warning/error
- `❌` - Critical failure

## Progress Bar Standards

Use `infra.progress.ProgressBar`:

```python
from infra.progress import ProgressBar

progress = ProgressBar(
    total=total_items,
    prefix="   ",        # 3-space indent
    width=40,            # Standard width
    unit="pages"         # or "items", "files", etc.
)

for item in items:
    # ... process item ...
    progress.update(current, suffix=f"{completed} ok")

progress.finish(f"   ✓ {completed}/{total} items processed")
```

## Logger Integration

During progress operations:
- **Visual progress**: Use `ProgressBar` for terminal output
- **File logging**: Use `logger.info()`, `logger.error()` for log files
- **NO stdout spam**: Avoid `logger.progress()` during visual progress

**Pattern:**
```python
# Terminal: Progress bar
progress.update(current, suffix=status)

# Log file: Errors only
if error:
    logger.error("Operation failed", page=page_num, error=error_msg)
```

## Examples

### Good: Clean Stage Flow

```
📚 Book Ingestion (hap-arnold)
   Title:     Hap Arnold
   Author:    Unknown
   Scan ID:   hap-arnold

   Extracting 340 pages at 600 DPI...
   [████████████████████████████████████████] 100% (340/340) - 23.3 pages/sec - 340 ok
   ✓ Extracted 340/340 pages

✅ Book registered: hap-arnold

📄 OCR Processing (hap-arnold)
   Processing 340 pages with Tesseract...
   [████████████████████████████████████████] 100% (340/340) - 8.1 pages/sec - 340 ok
   ✓ 340/340 pages processed

✅ OCR complete: 340/340 pages
```

### Bad: Inconsistent, Noisy

```
Processing: hap-arnold
   PDFs: 2
   Using filename as title: Hap Arnold
   Scan ID: hap-arnold

   📖 Book Info:
      Title:     Hap Arnold
      Author:    Unknown
      Scan ID:   hap-arnold
   Extracting pages from 2 PDF(s) at 600 DPI...
     Extracting 340 pages at 600 DPI (using 16 cores)...
     [progress...]
[12:26:21] ℹ️ [ocr] Processing book: Hap Arnold
[12:26:21] ℹ️ [ocr] Starting ocr stage
```

**Problems:**
- Mixed indentation (2 spaces, 3 spaces, 5 spaces)
- Redundant messages ("Extracting pages..." twice)
- Logger timestamps in terminal output
- Redundant book info (title shown 3 times)
- No clear stage boundaries

## Implementation Checklist

When adding terminal output:

- [ ] Use standard stage markers (📚 ✅)
- [ ] 3-space indentation for operations
- [ ] Use `ProgressBar` for progress tracking
- [ ] Clear completion messages
- [ ] No logger stdout spam
- [ ] Errors on new lines
- [ ] Test output with real data

## Related

- `infra/progress.py` - Progress bar utility
- `infra/logger.py` - File logging (not stdout)
- `NEXT_SESSION.md` - Terminal output improvements
