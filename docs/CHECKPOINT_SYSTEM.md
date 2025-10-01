# Checkpoint System

The AR Research pipeline includes a robust checkpoint system that allows stages to resume from failures without reprocessing completed work. This saves both time and API costs.

## Overview

**Key Features:**
- ✅ **Atomic, thread-safe** checkpoint files
- ✅ **Smart validation** - verifies actual output files, not just checkpoint state
- ✅ **Cost tracking** - estimates money saved by skipping completed work
- ✅ **Incremental updates** - checkpoint saved every 10 pages for safety
- ✅ **Zero-config** - just add `--resume` flag to any command

**What Gets Checkpointed:**
- Completed page numbers
- Processing costs (USD)
- Progress metrics (percent complete, remaining pages)
- Stage status (not_started, in_progress, completed, failed)
- Timestamps (created, updated, completed/failed)

## Quick Start

### Using --resume Flag

The `--resume` flag works on all stage commands and the full pipeline:

```bash
# Resume individual stages
uv run python ar.py ocr <scan-id> --resume
uv run python ar.py correct <scan-id> --resume
uv run python ar.py fix <scan-id> --resume
uv run python ar.py structure <scan-id> --resume

# Resume full pipeline (skips all completed stages/pages)
uv run python ar.py pipeline <scan-id> --resume
```

### Example: Recovering from a Failed Run

```bash
# Start processing a book
uv run python ar.py correct modest-lovelace

# (Process crashes after 250/447 pages)

# Resume from where it left off
uv run python ar.py correct modest-lovelace --resume
# ✅ Resuming: 250 pages already completed (saved ~$5.50)
# ⏳ Processing 197 remaining pages...
```

## How It Works

### Checkpoint Files

Checkpoints are stored per-stage in each book's directory:

```
~/Documents/book_scans/<scan-id>/
└── checkpoints/
    ├── ocr.json           # OCR stage checkpoint
    ├── correction.json    # Correction stage checkpoint
    ├── fix.json          # Fix stage checkpoint
    └── structure.json    # Structure stage checkpoint (future)
```

### Checkpoint Schema

Each checkpoint file follows this structure:

```json
{
  "version": "1.0",
  "scan_id": "modest-lovelace",
  "stage": "correction",
  "status": "in_progress",
  "created_at": "2025-10-01T10:00:00",
  "updated_at": "2025-10-01T10:30:00",
  "completed_pages": [1, 2, 3, 4, 5],
  "total_pages": 447,
  "progress": {
    "completed": 5,
    "remaining": 442,
    "percent": 1.1
  },
  "costs": {
    "total_usd": 0.11
  },
  "metadata": {},
  "validation": {
    "output_dir": "corrected",
    "file_pattern": "page_{:04d}.json"
  }
}
```

### Validation Logic

The checkpoint system doesn't blindly trust checkpoint files. When resuming:

1. **Scans output directory** for actual completed files
2. **Validates each file** - checks if it exists and contains valid JSON
3. **Updates checkpoint** with actual completed pages
4. **Returns only remaining pages** to process

This ensures robustness if:
- Checkpoint file gets corrupted
- Output files are manually deleted
- Previous run had partial failures

## Stage-Specific Behavior

### OCR Stage (`ar ocr --resume`)

- **What's checkpointed:** OCR extraction for each page
- **Output directory:** `ocr/page_*.json`
- **Resume logic:** Skips pages with valid OCR output
- **Cost savings:** Time only (OCR is free via Tesseract)

### Correction Stage (`ar correct --resume`)

- **What's checkpointed:** LLM-corrected pages
- **Output directory:** `corrected/page_*.json`
- **Resume logic:** Skips pages with valid corrected output
- **Cost savings:** ~$0.022/page (gpt-4o-mini)
- **Incremental saves:** Every 10 pages

### Fix Stage (`ar fix --resume`)

- **What's checkpointed:** Agent 4 targeted fixes
- **Output directory:** `corrected/page_*.json` (overwrites)
- **Resume logic:** Skips pages already fixed
- **Cost savings:** ~$0.01-0.05/page (Claude Sonnet 4)

### Structure Stage (`ar structure --resume`)

- **What's checkpointed:** Entire structured output
- **Output directory:** `structured/metadata.json`
- **Resume logic:** Simple check - if output exists, skip entire stage
- **Cost savings:** ~$0.50/book (Claude Sonnet 4.5)
- **Note:** Currently all-or-nothing (no per-page checkpointing)

### Pipeline (`ar pipeline --resume`)

When running the full pipeline with `--resume`:
- Each stage checks its own checkpoint
- Already-completed stages are skipped entirely
- Partially-completed stages resume from last checkpoint
- Shows total estimated cost savings across all stages

## Programming with Checkpoints

### Basic Usage

```python
from checkpoint import CheckpointManager

# Initialize checkpoint manager
checkpoint = CheckpointManager(
    scan_id="modest-lovelace",
    stage="correction"
)

# Get pages to process (resume-aware)
pages_to_process = checkpoint.get_remaining_pages(
    total_pages=447,
    resume=True,  # Set to False to reprocess everything
    start_page=1,
    end_page=447
)

# Process pages...
for page_num in pages_to_process:
    result = process_page(page_num)

    # Mark as completed (thread-safe)
    checkpoint.mark_completed(
        page_num=page_num,
        cost_usd=result['cost']
    )

# Mark stage complete
checkpoint.mark_stage_complete(metadata={
    'model': 'openai/gpt-4o-mini',
    'pages_processed': len(pages_to_process)
})
```

### Thread-Safe Operations

The checkpoint system is fully thread-safe for concurrent workers:

```python
from concurrent.futures import ThreadPoolExecutor

checkpoint = CheckpointManager(scan_id="book-id", stage="correction")
pages = checkpoint.get_remaining_pages(total_pages=447, resume=True)

def process_page(page_num):
    result = expensive_llm_call(page_num)
    # Thread-safe - multiple workers can call this concurrently
    checkpoint.mark_completed(page_num=page_num, cost_usd=result['cost'])
    return result

with ThreadPoolExecutor(max_workers=30) as executor:
    results = list(executor.map(process_page, pages))

checkpoint.mark_stage_complete()
```

### Manual Operations

```python
# Get current status
status = checkpoint.get_status()
print(f"Progress: {status['progress']['percent']}%")
print(f"Cost so far: ${status['costs']['total_usd']}")

# Force save checkpoint (normally auto-saves every 10 pages)
checkpoint.flush()

# Reset checkpoint (start over)
checkpoint.reset()

# Mark as failed
checkpoint.mark_stage_failed(error="API rate limit exceeded")

# Get progress summary
summary = checkpoint.get_progress_summary()
# "⏳ In progress - 250/447 (55.9%) - 197 remaining"
```

## Cost Savings

The checkpoint system tracks and estimates cost savings:

### Cost Tracking

```python
# Automatically tracked during processing
checkpoint.mark_completed(page_num=42, cost_usd=0.022)

# View total cost
status = checkpoint.get_status()
print(f"Total cost: ${status['costs']['total_usd']}")
```

### Cost Estimation

```python
# Estimate savings from skipping completed pages
savings = checkpoint.estimate_cost_saved(avg_cost_per_page=0.022)
print(f"Estimated savings: ${savings:.2f}")
```

**Example Cost Savings (447-page book):**
- Correction stage crashed at 50%: Resume saves **~$5.00**
- Correction stage crashed at 90%: Resume saves **~$9.00**
- Full pipeline re-run after completion: Resume saves **~$12.00**

## Safety Features

### Atomic Writes

Checkpoints use atomic writes to prevent corruption:

1. Write to temporary file (`correction.json.tmp`)
2. Validate temp file is valid JSON
3. Atomic rename to actual checkpoint file

If system crashes during write, the old checkpoint remains valid.

### Corruption Recovery

If checkpoint file is corrupted or has wrong version:
- Automatically creates fresh checkpoint
- Scans output directory for actually-completed pages
- Resumes from validated state

### Version Compatibility

Checkpoint files include a version field. If version changes:
- Old checkpoints are ignored
- New checkpoint created automatically
- Output validation ensures no work is lost

## Troubleshooting

### Checkpoint Not Resuming

**Problem:** Run with `--resume` but still reprocesses all pages

**Solutions:**
1. Check checkpoint file exists: `ls ~/Documents/book_scans/<scan-id>/checkpoints/`
2. Check output files exist: `ls ~/Documents/book_scans/<scan-id>/<stage>/`
3. Verify output files are valid JSON: `python -m json.tool <file>`

### Incorrect Cost Tracking

**Problem:** Checkpoint shows wrong cost for resumed run

**Note:** Currently checkpoint tracks cumulative cost across all runs. This is expected behavior. The "saved" cost is an estimate based on average per-page cost, not actual API costs from previous run.

### Pages Reprocessed After Crash

**Problem:** Some pages near crash point are reprocessed

**Explanation:** Checkpoints save every 10 pages by default. If crash happens between saves, last 1-9 pages may be reprocessed. This is intentional for performance.

**Solution:** Call `checkpoint.flush()` more frequently if needed (trades off I/O performance for more frequent saves).

### Resume Skips Too Many Pages

**Problem:** `--resume` skips pages that failed in previous run

**Explanation:** Checkpoint validates output files exist and are valid JSON. If previous run created output files that are incomplete/incorrect, checkpoint will trust them.

**Solution:**
1. Delete bad output files manually
2. Run without `--resume` to reprocess all pages
3. Or: Improve validation logic in `CheckpointManager.validate_page_output()`

## Performance Considerations

### I/O Overhead

- **Incremental saves:** Every 10 pages (~0.1-1ms per save)
- **Validation on resume:** Scans all output files (~0.01ms per file)
- **Typical overhead:** <1% of total processing time

### Recommended Settings

- **For fast stages (OCR):** Default settings work well
- **For expensive stages (Correction):** Consider more frequent saves if crashes are common
- **For single-call stages (Structure):** Simple "output exists" check is sufficient

## Future Enhancements

Potential improvements for future versions:

1. **Monitor Integration:** Show checkpoint status in `ar monitor` command
2. **Checkpoint CLI:** `ar checkpoint <scan-id> <stage>` for manual operations
3. **Auto-cleanup:** Delete checkpoints after successful pipeline completion
4. **Per-chapter checkpoints:** For structure stage
5. **Cost tracking:** Store actual per-page costs from API responses
6. **Partial page resume:** Skip completed sub-tasks within a page
7. **Checkpoint visualization:** Show checkpoint state in web UI

## Testing

The checkpoint system includes comprehensive unit tests:

```bash
# Run checkpoint tests
pytest tests/test_checkpoint.py -v

# Key test scenarios:
# - Save/load cycle
# - Resume skips completed pages
# - Thread safety (10 concurrent workers)
# - Validation logic
# - Corruption recovery
# - Version compatibility
```

## Summary

The checkpoint system provides:
- **Reliability:** Never lose progress from crashes/failures
- **Cost savings:** Avoid reprocessing expensive LLM calls
- **Safety:** Atomic writes, validation, corruption recovery
- **Performance:** Thread-safe for 30+ concurrent workers
- **Simplicity:** Just add `--resume` flag

For most use cases, simply add `--resume` to your commands and the system handles the rest automatically.
