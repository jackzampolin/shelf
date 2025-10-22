# Implementing a Pipeline Stage

## Overview

This guide explains how to implement a new pipeline stage using the BaseStage abstraction. For detailed architecture, see [Stage Abstraction](../architecture/stage-abstraction.md).

## Quick Reference

| Stage Type | Parallelization | Workers | Example |
|------------|-----------------|---------|---------|
| **CPU-bound** | ProcessPoolExecutor | `cpu_count()` | OCR (Tesseract) |
| **I/O-bound (LLM)** | ThreadPoolExecutor | `Config.max_workers` (30) | Correction, Label |
| **Deterministic** | ThreadPoolExecutor | Fixed (e.g., 8) | Merge |

## Stage Structure

**Location:** Implement in `pipeline/{stage_name}/__init__.py`

**Required components:**

1. **Output schema** (`schemas.py`) - What you write to disk
2. **Checkpoint schema** (`schemas.py`) - Metrics you track
3. **Report schema** (`schemas.py`, optional) - Quality subset for CSV
4. **Stage class** - Inherits from BaseStage with three hooks

## Step 1: Define Schemas

### Output Schema - Data Structure

What gets saved to `{stage}/page_NNNN.json`:

```python
# pipeline/{stage}/schemas.py
from pydantic import BaseModel, Field

class MyPageOutput(BaseModel):
    page_number: int
    blocks: List[BlockData]
    metadata: Dict[str, Any]
```

**See:** `pipeline/correction/schemas.py:CorrectionPageOutput` for example.

### Checkpoint Schema - Metrics

Extends `BasePageMetrics` (non-LLM) or `LLMPageMetrics` (LLM-based):

```python
from infra.pipeline.schemas import LLMPageMetrics

class MyPageMetrics(LLMPageMetrics):
    # LLMPageMetrics includes: cost, tokens, timing, model, provider
    # Add domain-specific quality metrics:
    total_corrections: int
    avg_confidence: float
```

**See:** `pipeline/correction/schemas.py:CorrectionPageMetrics` for full example.

### Report Schema - Quality Focus (Optional)

Subset of checkpoint for `report.csv`:

```python
class MyPageReport(BaseModel):
    page_num: int
    total_corrections: int  # Quality metric
    avg_confidence: float   # Quality metric
    # Omit: cost, tokens, timing (operational, not quality)
```

**When to use:** Always for LLM stages to highlight quality issues.

## Step 2: Implement Stage Class

**Location:** `pipeline/{stage_name}/__init__.py`

```python
from infra.pipeline.base_stage import BaseStage
from .schemas import MyPageOutput, MyPageMetrics, MyPageReport

class MyStage(BaseStage):
    name = "my_stage"           # Output directory name
    dependencies = ["prev_stage"]  # Required upstream stages

    output_schema = MyPageOutput
    checkpoint_schema = MyPageMetrics
    report_schema = MyPageReport  # Optional

    def __init__(self, max_workers: int = None):
        # For LLM stages:
        self.max_workers = max_workers or Config.max_workers
        self.model = Config.vision_model_primary

        # For CPU stages:
        # self.max_workers = max_workers or multiprocessing.cpu_count()

    def before(self, storage, checkpoint, logger):
        """Validate inputs - see Step 3"""
        pass

    def run(self, storage, checkpoint, logger):
        """Main processing - see Step 4"""
        return {"pages_processed": 0}

    def after(self, storage, checkpoint, logger, stats):
        """Post-processing - see Step 5"""
        super().after(storage, checkpoint, logger, stats)  # Generates report.csv
```

**See:** `pipeline/correction/__init__.py:CorrectionStage` for complete example.

## Step 3: Implement before() Hook

**Purpose:** Validate dependencies exist and are consistent. Fail fast before expensive processing.

**Common pattern:**

```python
def before(self, storage, checkpoint, logger):
    # Check dependency outputs exist
    prev_stage = storage.stage('prev_stage')
    prev_pages = prev_stage.list_output_pages(extension='json')

    if not prev_pages:
        raise FileNotFoundError(
            f"No outputs from {prev_stage}. Run that stage first."
        )

    # Verify consistency (e.g., 1-1 correspondence)
    source_pages = storage.stage('source').list_output_pages(extension='png')
    source_nums = {int(p.stem.split('_')[1]) for p in source_pages}
    prev_nums = {int(p.stem.split('_')[1]) for p in prev_pages}

    if source_nums != prev_nums:
        raise FileNotFoundError(
            f"Page count mismatch: {len(source_nums)} source, {len(prev_nums)} prev"
        )

    logger.info(f"Validated {len(prev_pages)} pages ready")
```

**What belongs here:**
- Input file existence checks
- Consistency validation
- Dependency verification

**What doesn't belong:**
- Data loading (do in run())
- Processing (belongs in run())
- Report generation (belongs in after())

**See:** `pipeline/correction/__init__.py:80-95` for real example.

## Step 4: Implement run() Hook

**Purpose:** Main processing logic. Return stats dict.

**Critical pattern:** Always use `checkpoint.get_remaining_pages(resume=True)` to support resume.

### Pattern A: CPU-Bound (ProcessPoolExecutor)

**When:** Tesseract OCR, image processing, CPU-intensive work

```python
def run(self, storage, checkpoint, logger):
    from concurrent.futures import ProcessPoolExecutor, as_completed

    # Get pages to process (resume-aware)
    total_pages = len(storage.stage('source').list_output_pages(extension='png'))
    remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

    logger.info(f"Processing {len(remaining)} pages")

    # Build work items
    futures = {}
    with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
        for page_num in remaining:
            future = executor.submit(_process_page_cpu, storage.book_dir, page_num)
            futures[future] = page_num

        # Collect results
        for future in as_completed(futures):
            page_num = futures[future]
            try:
                data, metrics = future.result()

                # Save atomically (includes checkpoint update)
                storage.stage(self.name).save_page(
                    page_num, data, metrics=metrics, schema=self.output_schema
                )

                logger.page_event(f"Completed page {page_num}", page=page_num)

            except Exception as e:
                logger.page_error(f"Failed page {page_num}", page=page_num, error=str(e))

    return {"pages_processed": len(remaining)}

# Must be top-level function for multiprocessing
def _process_page_cpu(book_dir: Path, page_num: int):
    # Load data, process, return (data, metrics)
    pass
```

**See:** `pipeline/ocr/__init__.py:90-140` for full example.

### Pattern B: I/O-Bound with LLM (ThreadPoolExecutor + LLMBatchClient)

**When:** LLM API calls, network I/O

```python
def run(self, storage, checkpoint, logger):
    from infra.llm.batch_client import LLMBatchClient, LLMRequest

    # Get pages
    total_pages = len(storage.stage('prev_stage').list_output_pages())
    remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

    logger.info(f"Processing {len(remaining)} pages with {self.model}")

    # Initialize LLM client
    batch_client = LLMBatchClient(
        max_workers=self.max_workers,
        max_retries=3,
        log_dir=storage.stage(self.name).output_dir / 'logs'
    )

    # Build requests
    requests = []
    for page_num in remaining:
        # Load input
        prev_data = storage.stage('prev_stage').load_page(
            page_num, schema=PrevPageOutput
        )

        # Build LLM request
        request = LLMRequest(
            request_id=f"page_{page_num:04d}",
            model=self.model,
            messages=[
                {"role": "user", "content": f"Process this: {prev_data}"}
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "page_output",
                    "schema": MyPageOutput.model_json_schema()
                }
            },
            metadata={"page_num": page_num}
        )
        requests.append(request)

    # Process batch with callbacks
    def on_result(result):
        page_num = result.metadata['page_num']

        # Extract data from structured response
        data = result.parsed_response  # Already validates against schema

        # Build metrics
        metrics = {
            'page_num': page_num,
            'cost_usd': result.cost_usd,
            'processing_time_seconds': result.total_time_seconds,
            'attempts': result.attempts,
            'tokens_total': result.usage['completion_tokens'],
            # ... LLMPageMetrics fields
            # ... domain-specific fields
        }

        # Save atomically
        storage.stage(self.name).save_page(page_num, data, metrics=metrics)
        logger.page_event(f"Completed page {page_num}", page=page_num)

    batch_client.process_batch(requests, on_result=on_result)

    return {"pages_processed": len(remaining)}
```

**See:** `pipeline/correction/__init__.py:100-200` for full example.

### Pattern C: Deterministic (No LLM)

**When:** Merge, transform, deterministic processing

```python
def run(self, storage, checkpoint, logger):
    from concurrent.futures import ThreadPoolExecutor, as_completed

    total_pages = len(storage.stage('source').list_output_pages(extension='png'))
    remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

    futures = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        for page_num in remaining:
            future = executor.submit(self._process_page, storage, page_num)
            futures[future] = page_num

        for future in as_completed(futures):
            page_num = futures[future]
            data, metrics = future.result()
            storage.stage(self.name).save_page(page_num, data, metrics=metrics)

    return {"pages_processed": len(remaining)}

def _process_page(self, storage, page_num):
    # Load inputs, merge/transform, return (data, metrics)
    pass
```

**See:** `pipeline/merged/__init__.py:80-150` for full example.

## Step 5: Implement after() Hook (Optional)

**Purpose:** Post-processing and validation. Default generates `report.csv` from checkpoint metrics.

**Default behavior** (usually sufficient):

```python
def after(self, storage, checkpoint, logger, stats):
    super().after(storage, checkpoint, logger, stats)  # Calls generate_report()
```

**Override when you need custom post-processing:**

```python
def after(self, storage, checkpoint, logger, stats):
    # Call parent first (generates report.csv)
    super().after(storage, checkpoint, logger, stats)

    # Custom: Extract metadata from first N pages
    metadata = self._extract_metadata(storage, logger)
    storage.update_metadata(metadata)
```

**See:** `pipeline/ocr/__init__.py:150-165` for metadata extraction example.

## Step 6: Integrate with CLI

**Location:** `shelf.py:cmd_process()`

Add stage to the stage mapping:

```python
# Map stage names to Stage instances
stage_map = {
    'ocr': OCRStage(max_workers=args.workers),
    'corrected': CorrectionStage(model=args.model, max_workers=args.workers),
    'labels': LabelStage(model=args.model, max_workers=args.workers),
    'merged': MergeStage(max_workers=8),
    'my_stage': MyStage(max_workers=args.workers),  # Add here
}
```

Now users can run: `uv run python shelf.py process <scan-id> --stage my_stage`

## Decision Points

### When to use ProcessPoolExecutor vs ThreadPoolExecutor?

**ProcessPoolExecutor:**
- CPU-bound work (Tesseract, image processing, compute-heavy)
- Can't share state between workers
- Requires top-level worker functions (picklable)

**ThreadPoolExecutor:**
- I/O-bound work (LLM API calls, file I/O)
- Can share state (e.g., progress tracking)
- Can use class methods as workers

### When to use vision models vs text-only?

**Vision (multimodal):**
- Need to see page images (correction, label classification)
- Cost: ~10x more than text-only
- Quality: Better for OCR correction, formatting detection

**Text-only:**
- Only need text (metadata extraction, text analysis)
- Cost: Cheaper
- Quality: Sufficient when visual context not needed

### How many workers?

**CPU-bound:** `multiprocessing.cpu_count()` - maximize CPU utilization
**LLM I/O-bound:** `Config.max_workers` (30) - balance speed vs rate limits
**Deterministic:** Fixed small number (8) - prevent resource contention

## Common Pitfalls

1. **Forgetting resume support** - Always use `checkpoint.get_remaining_pages(resume=True)`
2. **Not validating schemas** - Pass `schema=` to `save_page()` and `load_page()`
3. **Missing report_schema** - LLM stages should define to filter operational metrics
4. **Blocking in before()** - Only validate, don't load data or process
5. **Not handling failures** - Wrap page processing in try/except, log errors
6. **Hardcoding paths** - Use `storage.stage(name)` API, not manual path construction

## Testing Your Stage

Create `tests/pipeline/test_{stage}.py`:

```python
def test_my_stage(tmp_path):
    # Setup: Create fake inputs
    book_dir = tmp_path / "test-book"
    prev_stage_dir = book_dir / "prev_stage"
    prev_stage_dir.mkdir(parents=True)

    # Create fake input
    fake_page = PrevPageOutput(page_number=1, ...)
    (prev_stage_dir / "page_0001.json").write_text(fake_page.model_dump_json())

    # Run stage
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    stage = MyStage(max_workers=1)

    stats = run_stage(stage, storage)

    # Assert
    output = storage.stage("my_stage").load_page(1, schema=MyPageOutput)
    assert output.page_number == 1
```

**See:** `tests/infra/test_storage.py` for storage testing patterns.

## Summary

Implementing a stage requires:

1. **Schemas** - Output, checkpoint, report (3 Pydantic models)
2. **Class** - Extends BaseStage with name, dependencies, schemas
3. **before()** - Validate inputs, fail fast
4. **run()** - Main processing with resume support
5. **after()** - Optional custom post-processing (default: report generation)
6. **CLI integration** - Add to shelf.py stage map

**Key principles:**
- Always support resume (`get_remaining_pages(resume=True)`)
- Validate with schemas at boundaries
- Track costs and quality metrics
- Use appropriate parallelization strategy
- Follow existing patterns (see `pipeline/correction/` as reference)

See also:
- [Stage Abstraction](../architecture/stage-abstraction.md) - Design philosophy
- [Checkpoint & Resume](../architecture/checkpoint-resume.md) - Resume mechanisms
- [Logging & Metrics](../architecture/logging-metrics.md) - Observability integration
