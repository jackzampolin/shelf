# Implementing a Pipeline Stage

A one-page guide for building maintainable, resumable pipeline stages following the OCR pattern.

## Directory Structure

```
pipeline/your_stage/
├── __init__.py          # Stage class + BaseStage methods ONLY
├── status.py            # Progress tracking and status logic
├── storage.py           # Stage-specific storage operations
├── schemas/             # Pydantic schemas (one per file)
│   ├── __init__.py
│   ├── page_output.py   # Output schema
│   ├── page_metrics.py  # Checkpoint metrics schema
│   └── page_report.py   # Report schema (quality metrics only)
├── tools/               # Helper functions and workers
│   ├── processor.py
│   └── parallel_worker.py
└── llm_calls/           # Per-LLM-call organization (if needed)
    ├── schemas/
    │   └── response.py
    ├── prompts.py
    └── caller.py
```

## Core Files

### `__init__.py` - Stage Class Only

Contains ONLY the BaseStage implementation. No business logic.

```python
from infra.pipeline.base_stage import BaseStage
from .schemas import YourPageOutput, YourPageMetrics, YourPageReport
from .status import YourStatusTracker
from .storage import YourStageStorage

class YourStage(BaseStage):
    name = "your_stage"
    dependencies = ["prev_stage"]

    output_schema = YourPageOutput
    checkpoint_schema = YourPageMetrics
    report_schema = YourPageReport
    self_validating = True  # If multi-phase

    def __init__(self, max_workers=None):
        super().__init__()
        self.max_workers = max_workers
        self.status_tracker = YourStatusTracker(stage_name=self.name)
        self.stage_storage = YourStageStorage(stage_name=self.name)

    def get_progress(self, storage, checkpoint, logger):
        """Delegate to status tracker."""
        return self.status_tracker.get_progress(storage, checkpoint, logger)

    def before(self, storage, checkpoint, logger):
        """Validate dependencies exist."""
        # Check input files exist
        pass

    def run(self, storage, checkpoint, logger):
        """Execute all phases with resume support."""
        progress = self.get_progress(storage, checkpoint, logger)
        total_pages = progress["total_pages"]

        # Phase 1: Main processing
        if progress["status"] in ["not_started", "processing"]:
            remaining = progress["remaining_pages"]
            if len(remaining) > 0:
                logger.info(f"=== Phase 1: Processing {len(remaining)} pages ===")
                checkpoint.set_phase("processing")
                from .tools.processor import process_pages
                process_pages(storage, checkpoint, logger, remaining)
                progress = self.get_progress(storage, checkpoint, logger)

        # Phase 2: Report generation
        if len(progress["remaining_pages"]) == 0:
            if not progress["artifacts"]["report_exists"]:
                logger.info("=== Phase 2: Generate Report ===")
                checkpoint.set_phase("generating_report")
                from .tools.report_generator import generate_report
                generate_report(storage, checkpoint, logger, self.report_schema)

        # Mark complete
        if len(progress["remaining_pages"]) == 0 and progress["artifacts"]["report_exists"]:
            checkpoint.set_phase("completed")

        return {
            "pages_processed": total_pages - len(progress["remaining_pages"]),
            "total_cost_usd": progress["metrics"]["total_cost_usd"]
        }
```

### `status.py` - Progress Tracking

Calculates what work remains by reading disk state (ground truth).

```python
from enum import Enum
from .storage import YourStageStorage

class YourStageStatus(str, Enum):
    """Status progression for this stage."""
    NOT_STARTED = "not_started"
    PROCESSING = "processing"
    GENERATING_REPORT = "generating_report"
    COMPLETED = "completed"

class YourStatusTracker:
    """Tracks progress by checking files on disk."""

    def __init__(self, stage_name: str):
        self.stage_name = stage_name
        self.storage = YourStageStorage(stage_name=stage_name)

    def get_progress(self, storage, checkpoint, logger):
        """
        Calculate what work remains.

        Returns:
            {
                "status": "processing",
                "total_pages": 100,
                "remaining_pages": [5, 10, 23],
                "metrics": {"total_cost_usd": 1.23},
                "artifacts": {"report_exists": False}
            }
        """
        metadata = storage.load_metadata()
        total_pages = metadata.get('total_pages', 0)

        # Check which pages have outputs on disk
        completed_pages = self.storage.list_completed_pages(storage)
        remaining_pages = [p for p in range(1, total_pages + 1) if p not in completed_pages]

        # Check artifacts
        stage_storage = storage.stage(self.stage_name)
        report_exists = (stage_storage.output_dir / "report.csv").exists()

        # Determine status
        if len(remaining_pages) == total_pages:
            status = YourStageStatus.NOT_STARTED.value
        elif len(remaining_pages) > 0:
            status = YourStageStatus.PROCESSING.value
        elif not report_exists:
            status = YourStageStatus.GENERATING_REPORT.value
        else:
            status = YourStageStatus.COMPLETED.value

        # Calculate aggregate metrics
        all_metrics = checkpoint.get_all_metrics()
        total_cost = sum(m.get('cost_usd', 0) for m in all_metrics.values())

        return {
            "status": status,
            "total_pages": total_pages,
            "remaining_pages": remaining_pages,
            "metrics": {"total_cost_usd": total_cost},
            "artifacts": {"report_exists": report_exists}
        }
```

### `storage.py` - Stage-Specific Storage

All file I/O operations for this stage.

```python
from infra.storage.book_storage import BookStorage

class YourStageStorage:
    """Storage operations for your stage."""

    def __init__(self, stage_name: str):
        self.stage_name = stage_name

    def list_completed_pages(self, storage: BookStorage) -> list[int]:
        """Get list of completed page numbers by checking disk."""
        stage_storage = storage.stage(self.stage_name)
        output_pages = stage_storage.list_output_pages(extension='json')
        return sorted(output_pages)

    def load_custom_data(self, storage: BookStorage, filename: str):
        """Load stage-specific file (e.g., selection_map.json)."""
        stage_storage = storage.stage(self.stage_name)
        custom_file = stage_storage.output_dir / filename

        if custom_file.exists():
            return stage_storage.load_file(filename)
        return {}

    def save_custom_data(self, storage: BookStorage, filename: str, data: dict):
        """Save stage-specific file."""
        stage_storage = storage.stage(self.stage_name)
        stage_storage.save_file(filename, data)
```

## Key Patterns

### 1. Resume with if-gates

Structure `run()` as a series of if-gates that check progress:

```python
def run(self, storage, checkpoint, logger):
    progress = self.get_progress(storage, checkpoint, logger)

    # Each phase checks if work remains
    if needs_phase_1(progress):
        do_phase_1()
        progress = self.get_progress(...)  # Refresh

    if needs_phase_2(progress):
        do_phase_2()
        progress = self.get_progress(...)  # Refresh

    if all_done(progress):
        checkpoint.set_phase("completed")

    return stats
```

### 2. Ground truth from disk

`status.py` determines progress by checking files on disk, not checkpoint state:
- **Completed pages**: Check if output files exist
- **Artifacts**: Check if report.csv exists
- **Status**: Derive from what's on disk

### 3. Incremental processing

Use `checkpoint.mark_completed()` after each page for immediate resume:

```python
for page_num in remaining_pages:
    result = process_page(page_num)

    # Save output
    storage.stage(self.name).save_page(page_num, result, schema=self.output_schema)

    # Save metrics atomically
    checkpoint.mark_completed(page_num, cost_usd=0.1, metrics={...})
```

### 4. LLM call organization

For complex LLM calls, create a subdirectory:

```
llm_calls/correction/
├── schemas/
│   └── response.py     # Structured LLM response
├── prompts.py          # System and user prompts
└── caller.py           # LLM invocation logic
```

## Common Mistakes

❌ **Don't put business logic in `__init__.py`**
✅ **Keep `__init__.py` minimal** - only BaseStage methods

❌ **Don't check checkpoint for resume logic**
✅ **Check disk state** - files are ground truth

❌ **Don't batch checkpoint updates**
✅ **Mark completed immediately** - enables resume at any point

❌ **Don't put schemas in `__init__.py`**
✅ **One schema per file** in `schemas/` directory

## Testing Your Stage

```python
def test_my_stage(tmp_path):
    # Setup fake dependency
    book_dir = tmp_path / "test-book"
    prev_dir = book_dir / "prev_stage"
    prev_dir.mkdir(parents=True)

    # Create fake inputs
    for i in range(1, 6):
        (prev_dir / f"page_{i:04d}.json").write_text('{"page_number": ' + str(i) + '}')

    # Run stage
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    stage = MyStage()
    stats = run_stage(stage, storage)

    # Verify outputs
    my_dir = book_dir / "my_stage"
    assert (my_dir / "page_0001.json").exists()
    assert (my_dir / "report.csv").exists()
```

## Reference Implementation

See `pipeline/ocr/` for complete reference implementation with:
- Multi-phase processing (OCR → Selection → Metadata → Report)
- Complex status tracking (provider progress, selection states)
- Custom storage operations (selection_map.json, provider outputs)
- Vision LLM calls organized in `vision/` subdirectory
