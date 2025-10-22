# Pipeline Stage Patterns - Quick Reference

This document provides quick lookups for common stage implementation patterns.

## Quick Decision Tree

```
Is your stage CPU-intensive?
├─ YES (Tesseract, image processing, etc.)
│  ├─ Use: ProcessPoolExecutor
│  ├─ Workers: multiprocessing.cpu_count()
│  ├─ Pattern: Standalone worker functions
│  └─ See: Section 4 in STAGE_IMPLEMENTATION_GUIDE.md
│
└─ NO (Network I/O, file operations, etc.)
   ├─ Does it call LLMs?
   │  ├─ YES (Vision correction, labeling, etc.)
   │  │  ├─ Use: ThreadPoolExecutor + LLMBatchClient
   │  │  ├─ Workers: Config.max_workers (default 30)
   │  │  ├─ Pattern: Two-phase load + batch process
   │  │  └─ See: Section 5 in STAGE_IMPLEMENTATION_GUIDE.md
   │  │
   │  └─ NO (Data merging, deterministic transforms)
   │     ├─ Use: ThreadPoolExecutor or single-threaded
   │     ├─ Workers: Small fixed number (8) or 1
   │     ├─ Pattern: Simple parallel merge
   │     └─ Example: MergeStage in pipeline/merged/__init__.py
```

## Stage Class Template

```python
from infra.pipeline.base_stage import BaseStage
from infra.pipeline.schemas import BasePageMetrics, LLMPageMetrics
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger

class MyStage(BaseStage):
    # REQUIRED
    name = "my_stage"                    # Output directory name
    dependencies = ["previous_stage"]    # Upstream stage names
    
    # SHOULD SET
    input_schema = InputPageType        # From dependencies
    output_schema = OutputPageType      # What you write
    checkpoint_schema = MyPageMetrics   # Per-page metrics
    report_schema = MyPageReport        # Quality subset (optional)
    
    # CONSTRUCTOR
    def __init__(self, max_workers: int = None):
        # I/O-bound: Config.max_workers
        # CPU-bound: multiprocessing.cpu_count()
        self.max_workers = max_workers or self._default_workers()
        self.progress_lock = threading.Lock()
    
    # LIFECYCLE HOOKS
    def before(self, storage, checkpoint, logger):
        """Validate inputs exist and are consistent."""
        pass
    
    def run(self, storage, checkpoint, logger) -> Dict[str, Any]:
        """Process pages and return stats."""
        pages = checkpoint.get_remaining_pages(total_pages, resume=True)
        if not pages:
            return checkpoint.get_status().get('metadata', {})
        # ... process pages ...
        return {
            'pages_processed': completed,
            'pages_failed': failed,
            'total_cost_usd': total_cost
        }
    
    def after(self, storage, checkpoint, logger, stats):
        """Generate reports (optional - default generates CSV)."""
        super().after(storage, checkpoint, logger, stats)
```

## Schema Quick Reference

### Output Schema (What You Save)

```python
from pydantic import BaseModel, Field

class MyPageOutput(BaseModel):
    page_number: int = Field(..., ge=1)
    # Your fields here
    blocks: List[...] = Field(...)
    
    @field_validator('blocks')
    @classmethod
    def validate(cls, v):
        if not v:
            raise ValueError("Must have content")
        return v
```

**Design principle:** Exactly what gets written to disk.

### Checkpoint Schema (Metrics You Track)

```python
# Non-LLM stage
class MyPageMetrics(BasePageMetrics):
    page_num: int
    processing_time_seconds: float
    cost_usd: float
    # Your metrics
    my_quality_metric: float

# LLM stage
class MyPageMetrics(LLMPageMetrics):
    # Inherits: page_num, processing_time_seconds, cost_usd
    #          attempts, tokens_total, tokens_per_second, model_used, etc.
    # Add your metrics
    total_corrections: int = Field(..., ge=0)
    avg_confidence: float = Field(..., ge=0.0, le=1.0)
```

**Design principle:** Track quality metrics, not performance details.

### Report Schema (Quality Focus for CSV)

```python
class MyPageReport(BaseModel):
    page_num: int = Field(..., ge=1)
    # Only quality metrics
    total_corrections: int
    avg_confidence: float
    # Omit: tokens, timing, cost, attempts
```

**Design principle:** Subset of checkpoint schema for report.csv.

## Common Code Patterns

### Before Hook - Input Validation

```python
def before(self, storage, checkpoint, logger):
    # Get upstream outputs
    ocr_stage = storage.stage('ocr')
    ocr_pages = ocr_stage.list_output_pages(extension='json')
    
    if not ocr_pages:
        raise FileNotFoundError(
            f"No OCR outputs found in {ocr_stage.output_dir}. "
            f"Run OCR stage first."
        )
    
    # Verify correspondence
    source_pages = storage.stage('source').list_output_pages(extension='png')
    source_nums = set(int(p.stem.split('_')[1]) for p in source_pages)
    ocr_nums = set(int(p.stem.split('_')[1]) for p in ocr_pages)
    
    if source_nums != ocr_nums:
        raise FileNotFoundError(
            f"OCR and source pages don't match 1-1"
        )
    
    logger.info(f"Validated {len(ocr_pages)} pages")
```

### Run Hook - Standard Setup

```python
def run(self, storage, checkpoint, logger) -> Dict[str, Any]:
    # 1. Get total pages
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)
    if total_pages == 0:
        raise ValueError("total_pages not set")
    
    # 2. Log stage start
    logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
    logger.info(f"My Stage - Processing {total_pages} pages")
    
    # 3. Get remaining pages (handles resume)
    pages = checkpoint.get_remaining_pages(total_pages, resume=True)
    if not pages:
        logger.info("No pages to process (all complete)")
        return checkpoint.get_status().get('metadata', {})
    
    logger.info(f"Processing {len(pages)} pages")
    
    # 4. Do work
    # ... see executor patterns below ...
    
    # 5. Return stats
    return {
        'pages_processed': completed,
        'pages_failed': failed,
        'total_cost_usd': total_cost
    }
```

### Progress Tracking (Thread-Safe)

```python
from infra.pipeline.rich_progress import RichProgressBar

progress = RichProgressBar(total=len(pages), unit="pages")
completed = 0
failed = 0

for future in as_completed(futures):
    if success:
        completed += 1
    else:
        failed += 1
    
    # IMPORTANT: Use lock for thread safety
    with self.progress_lock:
        current = completed + failed
        suffix = f"{completed} ok" + (f", {failed} failed" if failed > 0 else "")
        progress.update(current, suffix=suffix)

progress.finish(f"   ✓ Processed {completed}/{len(pages)} pages")
```

## Parallelization Patterns

### ProcessPoolExecutor (CPU-Bound)

```python
from concurrent.futures import ProcessPoolExecutor, as_completed

def _process_page_worker(task: Dict) -> Tuple[bool, int, str, Dict]:
    """Standalone worker - cannot access self."""
    try:
        storage = BookStorage(
            scan_id=task['scan_id'],
            storage_root=Path(task['storage_root'])
        )
        page_num = task['page_number']
        
        # Do CPU-intensive work
        result = expensive_operation(storage, page_num)
        validated = OutputSchema(**result)
        
        return (True, page_num, None, validated.model_dump())
    except Exception as e:
        return (False, task['page_number'], str(e), None)

# In run()
tasks = [
    {
        'storage_root': str(storage.storage_root),
        'scan_id': storage.scan_id,
        'page_number': page_num
    }
    for page_num in pages
]

with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
    futures = {
        executor.submit(_process_page_worker, task): task['page_number']
        for task in tasks
    }
    
    for future in as_completed(futures):
        success, page_num, error, data = future.result()
        if success:
            storage.stage(self.name).save_page(
                page_num=page_num,
                data=data,
                schema=OutputSchema
            )
        else:
            logger.error(f"Page {page_num} failed", error=error)
```

### ThreadPoolExecutor + LLMBatchClient (LLM Stages)

```python
from infra.llm.batch_client import LLMBatchClient, LLMRequest

# Phase 1: Load pages in parallel
requests = []
with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
    futures = {
        executor.submit(load_page, page_num): page_num
        for page_num in pages
    }
    
    for future in as_completed(futures):
        result = future.result()
        if result:
            page_num, ocr_page, request = result
            requests.append(request)

# Phase 2: Process batch
batch_client = LLMBatchClient(
    max_workers=self.max_workers,
    max_retries=self.max_retries,
    verbose=True,
    log_dir=storage.stage(self.name).output_dir / "logs"
)

def on_result(result):
    """Called for each completed request."""
    page_num = result.request.metadata['page_num']
    if result.success:
        # Validate and save
        data = result.parsed_json
        validated = OutputSchema(**data)
        metrics = create_metrics(result, data)
        
        storage.stage(self.name).save_page(
            page_num=page_num,
            data=validated.model_dump(),
            schema=OutputSchema,
            cost_usd=result.cost_usd,
            metrics=metrics.model_dump()
        )
    else:
        logger.error(f"Page {page_num} failed", error=result.error)

batch_client.process_batch(requests, on_result=on_result)
```

## LLMRequest Structure

```python
from infra.llm.batch_client import LLMRequest

request = LLMRequest(
    # REQUIRED fields
    id=f"page_{page_num:04d}",
    model=self.model,
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ],
    
    # REQUIRED: response format
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": MyResponseModel.model_json_schema()
        }
    },
    
    # Vision models only
    images=[downsampled_image],
    
    # For callbacks
    metadata={
        'page_num': page_num,
        'storage': storage,
        'ocr_page': ocr_page
    }
)
```

## File Organization

```
pipeline/
  my_stage/
    __init__.py          # Stage class + worker functions
    schemas.py           # Output, checkpoint, report schemas
    prompts.py           # LLM prompts (if LLM stage)
    report.py            # Custom report generation (if needed)
    tests/
      test_stage.py      # Unit and integration tests
```

## Testing Checklist

```python
# In tests/test_my_stage.py

def test_before_validates_inputs(tmp_path):
    """before() should raise if inputs missing."""
    stage = MyStage()
    storage = BookStorage(scan_id="test", storage_root=tmp_path)
    checkpoint = CheckpointManager("test", "my_stage", storage_root=tmp_path)
    
    with pytest.raises(FileNotFoundError):
        stage.before(storage, checkpoint, MockLogger())

def test_run_respects_checkpoint_resume(tmp_path):
    """run() should only process remaining pages."""
    # 1. Run stage, complete pages 1-10
    # 2. Run again
    # 3. Verify only pages 11+ are processed

def test_output_schema_validation(tmp_path):
    """Output must validate against output_schema."""
    output_data = {...}
    validated = MyPageOutput(**output_data)
    assert validated.page_number == 1

def test_metrics_schema_validation(tmp_path):
    """Metrics must validate against checkpoint_schema."""
    metrics_data = {...}
    validated = MyPageMetrics(**metrics_data)
    assert validated.page_num > 0
```

## Common Pitfalls Checklist

- [ ] NOT using `checkpoint.get_remaining_pages(resume=True)`
- [ ] Progress updates without `self.progress_lock`
- [ ] Passing non-serializable objects in task dicts
- [ ] NOT validating before `save_page()`
- [ ] Missing `response_format` in LLM requests
- [ ] Hardcoding values instead of using `Config`
- [ ] Ignoring per-page failures (stopping instead of continuing)
- [ ] Returning empty pages dict without early return

## Key Files to Reference

- Base stage: `infra/pipeline/base_stage.py`
- Schemas: `infra/pipeline/schemas.py`
- OCR (CPU-bound): `pipeline/ocr/__init__.py`
- Correction (LLM): `pipeline/correction/__init__.py`
- Label (LLM): `pipeline/label/__init__.py`
- Merge (Deterministic): `pipeline/merged/__init__.py`
- Config: `infra/config.py`
- Checkpoint: `infra/storage/checkpoint.py`
- LLM Batch: `infra/llm/batch_client.py`

## Full Guide

See `docs/STAGE_IMPLEMENTATION_GUIDE.md` for comprehensive patterns and examples.
