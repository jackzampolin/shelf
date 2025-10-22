# Implementing a Pipeline Stage - Developer Guide

This guide extracts patterns from existing stage implementations (OCR, Correction, Label, Merge) to help you implement new stages consistently.

## Quick Reference

| Aspect | CPU-bound | I/O-bound | Deterministic |
|--------|-----------|-----------|---------------|
| **Example** | OCR (Tesseract) | Correction, Label (LLM) | Merge |
| **Executor** | ProcessPoolExecutor | ThreadPoolExecutor | ThreadPoolExecutor (small) |
| **Workers** | `multiprocessing.cpu_count()` | `Config.max_workers` (default 30) | Fixed (e.g., 8) |
| **LLM Calls** | No (metadata only) | Yes | No |
| **Cost Tracking** | $0 per page | Full telemetry | $0 |
| **Checkpoints** | Metrics only | Metrics + telemetry | Metrics only |

---

## 1. Stage Setup & Class Definition

Every stage extends `BaseStage` with these required components:

### Required Class Attributes

```python
from infra.pipeline.base_stage import BaseStage

class MyStage(BaseStage):
    # MUST be set
    name = "my_stage"  # Output directory name
    dependencies = ["previous_stage"]  # List of required upstream stages
    
    # SHOULD be set (enable schema validation & auto-reporting)
    input_schema = InputPageType  # Schema of data from dependencies
    output_schema = OutputPageType  # Schema of output data
    checkpoint_schema = MyPageMetrics  # Metrics tracked per page
    report_schema = MyPageReport  # Quality subset for reports (optional)
```

### Constructor Pattern

```python
def __init__(self, max_workers: int = None, other_param: str = None):
    """
    Standard pattern for stage initialization.
    
    Always support:
    - max_workers (optional) - defaults to Config.max_workers for I/O or cpu_count() for CPU
    - model (optional) - for LLM stages, defaults to Config.vision_model_primary
    - max_retries (optional) - for LLM stages, defaults to 3
    """
    # For I/O-bound stages (LLM calls)
    self.max_workers = max_workers if max_workers is not None else Config.max_workers
    self.model = model or Config.vision_model_primary
    self.max_retries = max_retries
    
    # For CPU-bound stages (Tesseract OCR)
    self.max_workers = max_workers or multiprocessing.cpu_count()
    
    # Thread safety for progress tracking
    self.progress_lock = threading.Lock()
```

**Key principle:** Always allow constructor parameters to override defaults, but fall back to `Config` values or computed defaults.

---

## 2. Schema Design Patterns

### Three-Schema Structure

Every stage uses **three schemas** with distinct purposes:

#### 2a. Output Schema - What You Write

Defines the data structure saved to `stage/page_NNNN.json`:

```python
class MyPageOutput(BaseModel):
    page_number: int = Field(..., ge=1)
    # Stage-specific fields
    blocks: List[BlockData] = Field(...)
    metadata: Dict[str, Any] = Field(...)
    
    # Validation
    @field_validator('blocks')
    @classmethod
    def validate_not_empty(cls, v):
        if not v:
            raise ValueError("Must have at least one block")
        return v
```

**Design principle:** Output schema = exactly what gets written to disk. No extra fields, no computed values.

#### 2b. Checkpoint Schema - What You Track

Tracks **per-page metrics** for progress and analysis:

```python
class BasePageMetrics(BaseModel):
    """All stages track these"""
    page_num: int = Field(..., ge=1)
    processing_time_seconds: float = Field(..., ge=0.0)
    cost_usd: float = Field(0.0, ge=0.0)

class LLMPageMetrics(BasePageMetrics):
    """LLM stages add these"""
    attempts: int = Field(..., ge=1)
    tokens_total: int = Field(..., ge=0)
    tokens_per_second: float = Field(..., ge=0.0)
    model_used: str
    provider: str
    # ... queue_time, execution_time, ttft, usage dict

class MyPageMetrics(LLMPageMetrics):
    """Your stage adds domain-specific metrics"""
    total_corrections: int = Field(..., ge=0)
    avg_confidence: float = Field(..., ge=0.0, le=1.0)
```

**Design principle:** 
- Non-LLM stages: extend `BasePageMetrics`
- LLM stages: extend `LLMPageMetrics`
- Include quality metrics (confidence, corrections, etc.)
- Do NOT include performance details that belong in logs

#### 2c. Report Schema - Quality Focus

**Optional** - Subset of checkpoint for CSV reports showing quality issues:

```python
class MyPageReport(BaseModel):
    """Minimal quality metrics for report.csv"""
    page_num: int = Field(..., ge=1)
    total_corrections: int = Field(..., ge=0)
    avg_confidence: float = Field(..., ge=0.0, le=1.0)
    # Omit: tokens, timing, cost, attempts
    # Include only: page-level quality issues
```

**When to use report_schema:**
- Always for LLM-based stages (to highlight quality issues)
- For CPU stages if you want quality-focused reporting
- Omit if checkpoint_schema is already minimal

**How it's used:** `BaseStage.generate_report()` extracts only report_schema fields from checkpoint metrics and writes to `report.csv`.

---

## 3. The Lifecycle Hooks - before(), run(), after()

### Before Hook - Validation & Setup

Called **before processing starts**. Use for dependency checks, not processing.

```python
def before(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger):
    """
    Validate all inputs exist and are consistent.
    
    Common checks:
    - Input files exist (list_output_pages)
    - File counts match (1-1, 1-1-1 correspondence)
    - Dependencies complete (check checkpoint status)
    
    Raise exception to abort stage.
    """
    # Get inputs from previous stages
    ocr_stage = storage.stage('ocr')
    ocr_pages = ocr_stage.list_output_pages(extension='json')
    
    if not ocr_pages:
        raise FileNotFoundError(
            f"No OCR outputs found in {ocr_stage.output_dir}. "
            f"Run OCR stage first."
        )
    
    # Verify 1-1 correspondence
    source_stage = storage.stage('source')
    source_pages = source_stage.list_output_pages(extension='png')
    
    source_nums = set(int(p.stem.split('_')[1]) for p in source_pages)
    ocr_nums = set(int(p.stem.split('_')[1]) for p in ocr_pages)
    
    if source_nums != ocr_nums:
        missing = source_nums - ocr_nums
        raise FileNotFoundError(
            f"Missing OCR for pages: {sorted(list(missing))[:10]}"
        )
    
    logger.info(f"Validated {len(ocr_pages)} pages ready for processing")
```

**What belongs in before():**
- Input file existence checks
- Consistency validation (same page numbers, counts match)
- Dependency verification
- Error messages with helpful context

**What does NOT belong:**
- Pre-loading large data (use lazy loading in run())
- Creating output directories (storage handles this)
- Progress tracking or logging volumes

### Run Hook - Main Processing

Your stage does its work here. **Subclasses MUST implement.**

```python
def run(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger) -> Dict[str, Any]:
    """
    Process pages and return stats.
    
    Returns:
        Dict with at least: {'pages_processed': N, 'pages_failed': N, 'total_cost_usd': X}
    """
    # 1. Load metadata and get total page count
    metadata = storage.load_metadata()
    total_pages = metadata.get('total_pages', 0)
    
    if total_pages == 0:
        raise ValueError("total_pages not set in metadata")
    
    # 2. Log stage start
    logger.start_stage(total_pages=total_pages, max_workers=self.max_workers)
    logger.info(f"My Stage - Processing {total_pages} pages")
    
    # 3. Get pages to process (handles resume from checkpoint)
    pages = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)
    
    if not pages:
        logger.info("No pages to process (all complete)")
        return checkpoint.get_status().get('metadata', {})
    
    logger.info(f"Processing {len(pages)} pages with {self.max_workers} workers")
    
    # 4. Do the processing (next sections show patterns)
    # ...
    
    # 5. Return stats
    return {
        'pages_processed': completed,
        'pages_failed': failed,
        'total_cost_usd': total_cost
    }
```

**Key pattern elements:**
- Always call `checkpoint.get_remaining_pages(total_pages, resume=True)` - handles pause/resume
- Track completed and failed counts separately
- Return dict with stats - used by after() hook and logging
- Progress tracking uses `RichProgressBar` or `RichProgressBarHierarchical`

### After Hook - Reports & Validation

Called **after run() completes successfully**. Default implementation generates report.csv.

```python
def after(self, storage: BookStorage, checkpoint: CheckpointManager, logger: PipelineLogger, stats: Dict[str, Any]):
    """
    Post-processing: validation, reports, metadata.
    
    Default (inherited): Generates report.csv from checkpoint metrics.
    Override to add custom post-processing.
    """
    # Generate standard quality report
    super().after(storage, checkpoint, logger, stats)
    
    # Custom post-processing (optional)
    corrections_used = stats.get('total_corrections_used', 0)
    logger.info(f"Merge complete", corrections_used=corrections_used)
```

**When to override after():**
- Add stage-specific post-processing (e.g., metadata extraction in OCR)
- Generate custom reports beyond CSV
- Validate output consistency
- Always call `super().after()` first to generate standard report

---

## 4. Parallelization Patterns

### Decision: Which Executor?

**ProcessPoolExecutor (CPU-bound):**
```python
from concurrent.futures import ProcessPoolExecutor

# Use for: CPU-intensive work (Tesseract OCR, image processing)
# NOT for: I/O calls (network, files), LLM APIs
# Workers: cpu_count()

with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
    future_to_page = {
        executor.submit(_process_page_worker, task): task['page_number']
        for task in tasks
    }
    
    for future in as_completed(future_to_page):
        page_num = future_to_page[future]
        try:
            result = future.result()
            # Process result
        except Exception as e:
            logger.error(f"Page {page_num} failed", error=str(e))
```

**ThreadPoolExecutor (I/O-bound):**
```python
from concurrent.futures import ThreadPoolExecutor

# Use for: Network calls (LLM APIs), file I/O, LLM batching
# Use with: LLMBatchClient for structured LLM requests
# Workers: Config.max_workers (default 30)

with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
    future_to_page = {
        executor.submit(load_page, page_num): page_num
        for page_num in pages
    }
    
    for future in as_completed(future_to_page):
        result = future.result()
        # Process result (non-blocking)
```

### Pattern: Parallel Page Loading (For LLM Stages)

Two-phase approach: load then process.

```python
# Phase 1: Load pages in parallel (cheap)
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

# Phase 2: Process batch with LLMBatchClient (expensive)
results = self.batch_client.process_batch(
    requests,
    on_event=progress_handler,
    on_result=save_result_handler
)
```

**Why two phases?**
- Decouples I/O (load) from LLM processing (batch)
- Allows progress tracking during loading
- Enables pre-validation before LLM calls
- LLMBatchClient handles queuing, rate limiting, retries

---

## 5. LLM Batch Processing Pattern

For stages that call LLMs (Correction, Label):

### Step 1: Initialize Batch Client

```python
# In run() method
stage_log_dir = storage.stage(self.name).output_dir / "logs"
self.batch_client = LLMBatchClient(
    max_workers=self.max_workers,
    # rate_limit uses Config.rate_limit_requests_per_minute by default
    max_retries=self.max_retries,
    retry_jitter=(1.0, 3.0),
    verbose=True,  # Enable per-request events
    log_dir=stage_log_dir,
    log_timestamp=logger.log_file.stem.split('_', 1)[1] if hasattr(logger, 'log_file') else None
)
```

### Step 2: Build LLMRequest Objects

```python
# For each page, create a request with:
# - Unique ID
# - Model
# - System + User messages
# - Vision images (if applicable)
# - response_format (REQUIRED - must be structured JSON schema)
# - metadata (for callbacks to access later)

request = LLMRequest(
    id=f"page_{page_num:04d}",
    model=self.model,
    messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt}
    ],
    images=[page_image],  # Vision stages only
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": response_schema_dict
        }
    },
    metadata={
        'page_num': page_num,
        'storage': storage,
        'ocr_page': ocr_page  # Reference to input data
    }
)
```

**Critical:** `response_format` is REQUIRED. Use Pydantic schema:
```python
schema = LLMResponseModel.model_json_schema()
```

### Step 3: Process Batch with Callbacks

```python
# Setup progress tracking
progress = RichProgressBarHierarchical(total=len(requests))
on_event = progress.create_llm_event_handler(
    batch_client=self.batch_client,
    start_time=time.time(),
    model=self.model,
    total_requests=len(requests),
    checkpoint=checkpoint
)

# Process with callbacks
results = self.batch_client.process_batch(
    requests,
    on_event=on_event,      # Progress tracking
    on_result=on_result     # Per-page callback
)

def on_result(result: LLMResult):
    """Called for each completed request (success or failure)."""
    page_num = result.request.metadata['page_num']
    
    if result.success:
        # result.parsed_json has LLM output
        # result.cost_usd, result.usage, result.tokens_received, etc.
        data = result.parsed_json
        
        # Validate, add metadata, save
        validated = OutputSchema(**data)
        metrics = create_metrics_from_result(result, data)
        
        storage.stage(self.name).save_page(
            page_num=page_num,
            data=validated.model_dump(),
            schema=OutputSchema,
            cost_usd=result.cost_usd,
            metrics=metrics.model_dump()
        )
    else:
        # Track failures, log errors
        logger.error(f"Page {page_num} failed", error=result.error)
        failed_pages.append(page_num)
```

**Why callbacks?** 
- Results arrive out-of-order (parallel processing)
- Immediate saving prevents memory buildup
- Telemetry events drive progress bar
- Failures handled promptly

---

## 6. Checkpoint & Progress Patterns

### Tracking Progress

```python
# Initialize progress bar
progress = RichProgressBar(
    total=len(pages),
    prefix="   ",
    width=40,
    unit="pages"
)

# Update as you go
completed = 0
failed = 0

for future in as_completed(futures):
    success = future.result()
    if success:
        completed += 1
    else:
        failed += 1
    
    # Thread-safe update
    with self.progress_lock:
        current = completed + failed
        suffix = f"{completed} ok" + (f", {failed} failed" if failed > 0 else "")
        progress.update(current, suffix=suffix)

# Finish
progress.finish(f"   ✓ Processed {completed}/{len(pages)} pages")
```

### Checkpoint Management

```python
# Get remaining pages (respects pause/resume)
pages = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)

# Mark page complete (thread-safe)
checkpoint.mark_completed(page_num, cost_usd=0.02)

# Mark stage complete
checkpoint.mark_stage_complete()

# Query status
status = checkpoint.get_status()
```

**Important:** `save_page()` automatically calls `checkpoint.mark_completed()`:
```python
# This handles both saving AND checkpointing
storage.stage(self.name).save_page(
    page_num=page_num,
    data=validated.model_dump(),
    schema=OutputSchema,
    cost_usd=result.cost_usd,
    metrics=metrics.model_dump()
)
```

---

## 7. Error Handling Strategies

### Before Hook - Fail Fast

```python
def before(self, storage, checkpoint, logger):
    # Check dependencies first
    if not upstream_stage_output_exists:
        raise FileNotFoundError("Upstream stage incomplete")
    
    # Check consistency
    if counts_dont_match:
        raise ValueError("Input files inconsistent")
```

### Run Hook - Per-Page Resilience

```python
for future in as_completed(futures):
    try:
        success, data = future.result()
        if success:
            # Save and checkpoint
            checkpoint.mark_completed(page_num)
        else:
            # Track failure
            failed_pages.append(page_num)
            logger.error(f"Page {page_num} failed", error=data)
    except Exception as e:
        # Unexpected error
        failed_pages.append(page_num)
        logger.error(f"Page {page_num} exception", error=str(e))
```

**Pattern:**
- Catch per-page failures (don't stop processing)
- Log detailed errors for analysis
- Track failed pages separately
- Return stats with failure count
- Continue to after() hook for reporting

### After Hook - Output Validation

```python
def after(self, storage, checkpoint, logger, stats):
    # Validate outputs match expectation
    if stats['pages_failed'] > 0:
        logger.warning(f"{stats['pages_failed']} pages failed")
    
    # Generate report
    super().after(storage, checkpoint, logger, stats)
```

---

## 8. Structured Output (JSON Schema) Pattern

For LLM-based stages, use **page-specific schemas** to prevent LLM creativity:

```python
def build_page_specific_schema(ocr_page: OCRPageOutput) -> dict:
    """
    Generate JSON schema tailored to THIS page's structure.
    
    Constrains LLM output to match page structure exactly:
    - Block count: minItems = maxItems = len(ocr_page.blocks)
    - Paragraph count per block: constrained to match OCR
    
    This prevents LLM from adding/removing blocks or paragraphs.
    """
    import copy
    
    base_schema = OutputModel.model_json_schema()
    schema = copy.deepcopy(base_schema)
    
    # Constraint 1: Block count must match
    num_blocks = len(ocr_page.blocks)
    schema['properties']['blocks']['minItems'] = num_blocks
    schema['properties']['blocks']['maxItems'] = num_blocks
    
    # Constraint 2: Paragraph count per block must match
    block_items = []
    for block in ocr_page.blocks:
        para_count = len(block.paragraphs)
        block_schema = copy.deepcopy(schema['$defs']['BlockType'])
        
        block_schema['properties']['paragraphs']['minItems'] = para_count
        block_schema['properties']['paragraphs']['maxItems'] = para_count
        
        block_items.append(block_schema)
    
    # Replace items with prefixItems for tuple validation
    schema['properties']['blocks']['prefixItems'] = block_items
    schema['properties']['blocks']['items'] = False  # No extra items
    
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": schema
        }
    }
```

**Why this matters:**
- Vision models hallucinate structure (adds blocks that don't exist)
- Page-specific schema forces LLM to preserve structure
- Output is guaranteed to align with input structure
- Merging stages depend on 1-1 correspondence

---

## 9. Worker Process Pattern (CPU-bound)

For ProcessPoolExecutor, use standalone worker functions (not methods):

```python
def _process_page_worker(task: Dict[str, Any]) -> Tuple[bool, int, str, Dict]:
    """
    Standalone worker function for parallel CPU-bound processing.
    
    Runs in separate process via ProcessPoolExecutor.
    Cannot access instance state (it's in a different process).
    
    Args:
        task: Dict with all needed parameters (serializable)
    
    Returns:
        (success, page_num, error_msg, page_data)
    """
    try:
        # Reconstruct resources in worker process
        storage = BookStorage(
            scan_id=task['scan_id'],
            storage_root=Path(task['storage_root'])
        )
        
        page_number = task['page_number']
        
        # Do work
        page_file = storage.stage('source').output_page(page_number)
        image = Image.open(page_file)
        
        # Process (CPU-intensive)
        result = _expensive_cpu_work(image)
        
        # Validate output
        validated = OutputSchema(**result)
        
        return (True, page_number, None, validated.model_dump())
    
    except Exception as e:
        return (False, task['page_number'], str(e), None)


# In run() method:
tasks = [
    {
        'storage_root': str(storage.storage_root),
        'scan_id': storage.scan_id,
        'page_number': page_num
    }
    for page_num in pages
]

with ProcessPoolExecutor(max_workers=self.max_workers) as executor:
    future_to_page = {
        executor.submit(_process_page_worker, task): task['page_number']
        for task in tasks
    }
    
    for future in as_completed(future_to_page):
        success, page_num, error, data = future.result()
        # Handle result
```

**Critical constraints:**
- Worker function must be module-level (picklable)
- Cannot reference instance variables (`self.x`)
- Pass all data as task dict
- Return tuple (serializable)
- Reconstruct storage/resources in worker

---

## 10. Vision Model Integration

For stages using vision models (Correction, Label, metadata extraction):

### Image Preparation

```python
from infra.utils.pdf import downsample_for_vision

# Load and prepare image
page_image = Image.open(page_file)
page_image = downsample_for_vision(page_image)  # Reduces to 768 max dimension
```

**Why downsample?**
- Vision API charges per image token
- 768px max dimension = ~100 vision tokens (vs 4000+ at full resolution)
- Sufficient for OCR correction and block classification
- Reduces cost 10-40x with minimal quality loss

### Building Prompts

```python
def build_user_prompt(page_num: int, total_pages: int, book_metadata: Dict, ocr_data: Dict) -> str:
    """
    Build page-specific prompt with context.
    
    Include:
    - Page number (for context)
    - Total pages (for book size context)
    - Book metadata (title, author for subject knowledge)
    - OCR text structure (blocks, paragraphs for visual alignment)
    """
    return f"""<task>
Analyze page {page_num}/{total_pages} of "{book_metadata.get('title', 'Unknown')}".

<ocr_structure>
{json.dumps(ocr_data, indent=2)}
</ocr_structure>

<task_instructions>
[Your task-specific instructions here]
</task_instructions>

Return ONLY a JSON object matching the response schema.
"""
```

---

## 11. Decision Tree: Should You Implement a Stage?

### Yes, if:
- Processing is deterministic or parallelizable
- Output schema is well-defined
- Can be tested in isolation
- Cost or time is material

### Maybe if:
- Depends on many external services
- Output is highly variable
- No clear input/output boundary

### No, if:
- Better as a post-processing script
- Requires manual human input
- One-time operation

### Example: Should Metadata Extraction be a Stage?

**Current:** Tool in OCR's after() hook
**Could be:** Separate stage between OCR and Correction

**Reasons to make it a stage:**
- Reusable (metadata used by Correction and Label)
- Checkpointable (avoid re-extracting on resume)
- Testable independently
- Clear input (OCR outputs) and output (metadata.json)

**Pattern to follow:**
```python
class MetadataStage(BaseStage):
    name = "metadata"
    dependencies = ["ocr"]
    
    input_schema = None  # Reads OCR outputs directly
    output_schema = None  # Updates metadata.json, not per-page files
    checkpoint_schema = MetadataPageMetrics
    
    def before(...):
        # Verify OCR outputs exist
        pass
    
    def run(...):
        # Run once (metadata extracted from first N pages)
        # OR once per page to track confidence per page
        pass
    
    def after(...):
        super().after(...)
        # Validate metadata quality
```

---

## 12. Common Pitfalls & Solutions

### Pitfall 1: Ignoring resume from checkpoint

**Wrong:**
```python
pages = list(range(1, total_pages + 1))  # Always processes all pages
```

**Right:**
```python
pages = checkpoint.get_remaining_pages(total_pages=total_pages, resume=True)
if not pages:
    logger.info("No pages to process (all complete)")
    return checkpoint.get_status().get('metadata', {})
```

### Pitfall 2: Not thread-safe progress tracking

**Wrong:**
```python
completed += 1
progress.update(completed)  # Race condition!
```

**Right:**
```python
with self.progress_lock:
    completed += 1
    progress.update(completed)
```

### Pitfall 3: Mixing serializable and non-serializable in tasks

**Wrong:**
```python
task = {
    'page_num': 1,
    'logger': logger,  # NOT SERIALIZABLE
}
executor.submit(_worker, task)
```

**Right:**
```python
task = {
    'page_num': 1,
    'storage_root': str(storage.storage_root),  # Strings, not objects
    'scan_id': storage.scan_id,
}
executor.submit(_worker, task)
# In worker, reconstruct logger if needed
```

### Pitfall 4: Not validating output before saving

**Wrong:**
```python
storage.stage(self.name).save_page(page_num=page_num, data=page_data)
# What if page_data is missing required fields?
```

**Right:**
```python
validated = OutputSchema(**page_data)  # Validates
storage.stage(self.name).save_page(
    page_num=page_num,
    data=validated.model_dump(),
    schema=OutputSchema
)
```

### Pitfall 5: Missing response_format in LLM requests

**Wrong:**
```python
request = LLMRequest(
    id=f"page_{page_num}",
    model=self.model,
    messages=[...],
    # Missing response_format!
)
```

**Right:**
```python
request = LLMRequest(
    id=f"page_{page_num}",
    model=self.model,
    messages=[...],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "response",
            "strict": True,
            "schema": schema_dict
        }
    }
)
```

### Pitfall 6: Not using Config defaults

**Wrong:**
```python
def __init__(self):
    self.max_workers = 30  # Hardcoded
```

**Right:**
```python
def __init__(self, max_workers: int = None):
    self.max_workers = max_workers if max_workers is not None else Config.max_workers
```

---

## 13. Testing Your Stage

### Unit Test Pattern

```python
import pytest
from pathlib import Path
import json

def test_stage_before_validation(tmp_path):
    """Test before() hook validates inputs."""
    storage = BookStorage(scan_id="test", storage_root=tmp_path)
    checkpoint = CheckpointManager("test", "my_stage", storage_root=tmp_path)
    logger = MockLogger()
    
    stage = MyStage()
    
    # Should raise if inputs don't exist
    with pytest.raises(FileNotFoundError):
        stage.before(storage, checkpoint, logger)

def test_stage_run_checkpoint_resume(tmp_path):
    """Test run() respects checkpoint resume."""
    # Setup: process pages 1-5, then resume
    # Verify only pages 6+ are processed on second call

def test_stage_output_schema_validation(tmp_path):
    """Test output passes output_schema validation."""
    # Generate test output data
    # Verify it validates against output_schema
```

### Integration Test Pattern

```python
def test_full_pipeline_integration(tmp_path):
    """Test my stage in context with upstream stages."""
    # 1. Run OCR stage
    # 2. Run correction stage
    # 3. Run my stage
    # 4. Verify outputs, metrics, reports
```

---

## 14. Checklist: Before Submitting Stage

- [ ] Class attributes set: `name`, `dependencies`, `input_schema`, `output_schema`, `checkpoint_schema`
- [ ] `before()` validates inputs and dependencies
- [ ] `run()` calls `checkpoint.get_remaining_pages(resume=True)`
- [ ] Progress tracking uses `self.progress_lock`
- [ ] Output validated before saving: `OutputSchema(**data)`
- [ ] `save_page()` handles checkpointing automatically
- [ ] Return dict with `pages_processed`, `pages_failed`, `total_cost_usd`
- [ ] `after()` calls `super().after()` for report generation
- [ ] Schemas have descriptive Field annotations
- [ ] Error messages reference next steps (e.g., "Run OCR stage first")
- [ ] Tests cover happy path and resume from checkpoint
- [ ] Documentation: module docstring explains stage purpose
- [ ] Config defaults used, not hardcoded

---

## References

**Key Files:**
- Base stage: `/infra/pipeline/base_stage.py`
- Schemas: `/infra/pipeline/schemas.py`
- OCR stage (CPU-bound): `/pipeline/ocr/__init__.py`
- Correction stage (LLM): `/pipeline/correction/__init__.py`
- Label stage (LLM): `/pipeline/label/__init__.py`
- Merge stage (deterministic): `/pipeline/merged/__init__.py`
- Config: `/infra/config.py`
- Checkpoint: `/infra/storage/checkpoint.py`
- LLM Batch: `/infra/llm/batch_client.py`

**Key Imports:**
```python
from infra.pipeline.base_stage import BaseStage
from infra.pipeline.schemas import BasePageMetrics, LLMPageMetrics
from infra.storage.book_storage import BookStorage
from infra.storage.checkpoint import CheckpointManager
from infra.pipeline.logger import PipelineLogger
from infra.config import Config
from infra.llm.batch_client import LLMBatchClient, LLMRequest, LLMResult
from infra.pipeline.rich_progress import RichProgressBar, RichProgressBarHierarchical
```

