# Storage System Architecture

## Purpose

Three-tier abstraction for managing book processing data with thread-safe operations, atomic writes, and clean separation between library-level, book-level, and stage-level concerns.

## Three-Tier Hierarchy

**Location:** `infra/storage/`

```
LibraryStorage (library.py)
    └── scan filesystem for books, create BookStorage instances

BookStorage (book_storage.py)
    └── manage book metadata, factory for StageStorage

StageStorage (stage_storage.py)
    └── generic stage I/O, lazy CheckpointManager initialization

CheckpointManager (checkpoint.py)
    └── progress tracking per stage
```

### Tier 1: LibraryStorage

**Responsibility:** Library-wide operations and book discovery

**Key operations:**
- `list_books()` - Scan filesystem for book directories
- `get_book(scan_id)` - Create BookStorage for specific book
- `create_book(scan_id)` - Initialize new book directory

**Design:** Filesystem as source of truth - no `library.json` catalog. Eliminates sync problems.

### Tier 2: BookStorage

**Responsibility:** Book-level metadata and stage access factory

**Key operations:**
- `load_metadata()` / `update_metadata()` - Thread-safe metadata operations
- `stage(name: str)` - Generic factory returns StageStorage for any stage

**Thread safety:** `_metadata_lock` protects metadata.json updates.

**Generic factory pattern:**
```python
storage.stage('ocr')      # Works automatically
storage.stage('corrected')
storage.stage('new-stage')  # No code changes needed
```

### Tier 3: StageStorage

**Responsibility:** Generic stage-specific I/O for any stage

**Key operations:**
- `save_page(page_num, data, metrics, schema)` - Atomic write with checkpoint update
- `load_page(page_num, schema)` - Load with validation
- `list_output_pages()` - List all page_NNNN.json files

**Thread safety:** `RLock` (reentrant lock) protects checkpoint property initialization.

**Why RLock?** The `checkpoint` property calls `ensure_directories()` which also acquires the lock. Same thread can reenter without deadlock.

### Tier 4: CheckpointManager

**Responsibility:** Progress tracking and resumption per stage

**Lazy initialization:** Created on first access via StageStorage.checkpoint property, not upfront.

See `checkpoint-resume.md` for detailed architecture.

## Thread Safety Design

### Lock Hierarchy (Prevents Deadlocks)

```
Level 1: LibraryStorage (no lock - read-only)
Level 2: BookStorage._metadata_lock (Lock)
Level 3: StageStorage._lock (RLock)
Level 4: CheckpointManager._lock (Lock)
```

**Rule:** Always acquire in order, never backwards.

### Thread Safety Guarantees

**BookStorage:**
- Metadata writes are atomic (temp file → validate → rename)
- `_metadata_lock` ensures only one writer at a time

**StageStorage:**
- `save_page()` is thread-safe (atomic write + checkpoint update)
- `checkpoint` property uses double-checked locking for lazy init
- Multiple workers can call `save_page()` concurrently

**CheckpointManager:**
- `mark_completed()` is idempotent and thread-safe
- `page_metrics` updates protected by `_lock`

## Atomic Write Pattern

**Used in three places:** BookStorage metadata, StageStorage pages, CheckpointManager checkpoint

```python
# 1. Write to temp file
temp_path = target_path.with_suffix('.tmp')
temp_path.write_text(json.dumps(data))

# 2. Flush to disk (ensure OS writes to storage)
with temp_path.open('r+b') as f:
    os.fsync(f.fileno())

# 3. Validate (optional but recommended)
validate_json(temp_path)

# 4. Atomic rename
temp_path.rename(target_path)
```

**Guarantee:** If process crashes, only .tmp file corrupted, never target file.

**Why os.fsync()?** OS may buffer writes in RAM. Crash before flush loses data. fsync() forces persistence.

## File Layout Conventions

```
{storage_root}/             (e.g., ~/Documents/book_scans/)
└── {scan_id}/              (e.g., "modest-lovelace")
    ├── metadata.json       (Book metadata)
    ├── source/             (Source images)
    ├── ocr/
    │   ├── page_0001.json  (OCRPageOutput)
    │   ├── report.csv      (Quality report)
    │   ├── .checkpoint     (Progress state)
    │   └── logs/
    ├── corrected/
    │   ├── page_0001.json  (CorrectionPageOutput)
    │   ├── report.csv
    │   ├── .checkpoint
    │   └── logs/
    └── images/             (Extracted image regions)
```

**Naming conventions:**
- Pages: `page_NNNN.json` (zero-padded, alphanumeric sorting)
- Logs: `{stage}_{timestamp}.jsonl`
- Checkpoint: `.checkpoint` (hidden file)
- Reports: `report.csv`

**Stage ownership invariant:** A stage can ONLY write to its own output directory.

## CheckpointManager Integration

### save_page() Atomicity

`save_page()` atomically saves data AND updates checkpoint:

```python
def save_page(self, page_num, data, metrics=None, schema=None):
    # 1. Validate against schema
    if schema:
        validated = schema(**data)
        data = validated.model_dump()

    # 2. Write to temp file
    temp_path = self.output_dir / f"page_{page_num:04d}.json.tmp"
    temp_path.write_text(json.dumps(data, indent=2))

    # 3. Flush to disk
    with temp_path.open('r+b') as f:
        os.fsync(f.fileno())

    # 4. Atomic rename
    target_path = self.output_dir / f"page_{page_num:04d}.json"
    temp_path.rename(target_path)

    # 5. Update checkpoint (thread-safe, idempotent)
    if metrics:
        self.checkpoint.mark_completed(page_num, metrics=metrics)
```

**Guarantee:** Page file and checkpoint updated atomically (both or neither).

## Resume Safety via Scanning

On resume, checkpoint validates against filesystem:

```python
def get_remaining_pages(self, total_pages, resume=True):
    if resume:
        # Sync checkpoint with actual filesystem state
        valid_pages = self.scan_existing_outputs()
        # Update page_metrics to match reality

    # Return only pages not in page_metrics
    completed = set(self.page_metrics.keys())
    return [p for p in range(1, total_pages+1) if p not in completed]
```

**Why scan?** Files are facts, checkpoint is progress tracking. Facts win.

**Example:** Checkpoint says page 42 complete, but file corrupted → remove from page_metrics → re-process.

## Generic Stage Factory Pattern

`BookStorage.stage(name)` works for ANY stage name:

```python
def stage(self, stage_name: str) -> StageStorage:
    """Get stage storage for any stage (generic factory)."""
    return StageStorage(book_dir=self.book_dir, stage_name=stage_name)
```

**Benefits:**
1. No hardcoding - Add new stages without modifying storage code
2. Consistent interface - All stages use same API
3. Dynamic access - Can iterate over stage names programmatically

## Design Rationale

### Why Three Tiers?

| Tier | Concern | Why Separate |
|------|---------|-------------|
| LibraryStorage | Finding books | Library ≠ individual book |
| BookStorage | Book metadata + stage factory | Metadata shared across stages |
| StageStorage | Stage I/O | Each stage independent |
| CheckpointManager | Progress tracking | Progress ≠ data storage |

### Why Generic Over Inheritance?

Instead of `OCRStorage extends BaseStorage`, we have:

```python
# Generic approach (what we use):
storage.stage('ocr').save_page(...)
storage.stage('new-stage').save_page(...)  # Works immediately

# Would have required:
class OCRStorage(BaseStorage): ...
class NewStageStorage(BaseStorage): ...  # New class for each stage
```

**Why generic wins:** Fewer classes, new stages work immediately, consistent API, no inheritance complexity.

## Performance Characteristics

**Atomic writes:** ~2x slower than naive write, but zero corruption risk. Worth it for data integrity.

**Lock contention:** Minimal with 16 workers. mark_completed() is fast (<1ms).

**Filesystem scanning:** Negligible overhead (<10ms) compared to processing time.

## Common Patterns

### Read Dependency, Write Own

```python
# In CorrectionStage.run()
ocr_data = storage.stage('ocr').load_page(page_num, schema=OCRPageOutput)
corrected = correct_page(ocr_data)
storage.stage('corrected').save_page(page_num, corrected, metrics=metrics)
```

### Multi-Stage Read, Single Write

```python
# In MergeStage.run()
ocr = storage.stage('ocr').load_page(page_num)
corrected = storage.stage('corrected').load_page(page_num)
labels = storage.stage('labels').load_page(page_num)
merged = merge_three_sources(ocr, corrected, labels)
storage.stage('merged').save_page(page_num, merged)
```

## Summary

The three-tier storage architecture provides:

1. **Separation** - Library vs Book vs Stage vs Progress concerns
2. **Thread safety** - Atomic writes, lock hierarchy, reentrant locks
3. **Genericity** - Works for any stage without code changes
4. **Durability** - Atomic writes prevent corruption
5. **Resume safety** - Filesystem is source of truth
6. **Simplicity** - Consistent API across all tiers

**Key insight:** Separating storage (data) from checkpointing (progress) enables generic stage support, independent progress tracking, clean testing, and reliable resume.

See also:
- `stage-abstraction.md` - How stages use storage
- `checkpoint-resume.md` - Checkpoint architecture
- `logging-metrics.md` - Observability integration
