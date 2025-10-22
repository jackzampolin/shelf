# Stage Abstraction Architecture

## Purpose

The Stage abstraction solves: **how to compose independent, resumable, testable processing stages while maintaining type safety and cost visibility in LLM-powered pipelines**.

Traditional approaches (monolithic scripts, function chains, task queues) fail to address independence, resumability, type safety, cost tracking, testability, and traceability simultaneously.

## Solution: BaseStage Contract

**Location:** `infra/pipeline/base_stage.py`

```python
class MyStage(BaseStage):
    name = "my_stage"           # Output directory name
    dependencies = ["prev_stage"]  # Required upstream stages

    output_schema = MyPageOutput        # What you write
    checkpoint_schema = MyPageMetrics   # What you track
    report_schema = MyPageReport        # What you report (optional)

    def before(storage, checkpoint, logger): pass  # Pre-flight validation
    def run(storage, checkpoint, logger): {...}    # Main processing (REQUIRED)
    def after(storage, checkpoint, logger, stats): pass  # Post-processing
```

## Three-Hook Lifecycle

### before() - Pre-flight Validation

**Purpose:** Validate dependencies exist and are consistent. **Fail fast before expensive computation.**

```python
def before(self, storage, checkpoint, logger):
    ocr_pages = storage.stage('ocr').list_output_pages(extension='json')
    if not ocr_pages:
        raise FileNotFoundError("No OCR outputs. Run OCR stage first.")

    source_nums = {int(p.stem.split('_')[1]) for p in source_pages}
    ocr_nums = {int(p.stem.split('_')[1]) for p in ocr_pages}
    if source_nums != ocr_nums:
        raise FileNotFoundError(f"Page count mismatch")
```

**What belongs:** Input checks, consistency validation, dependency verification
**What doesn't:** Data loading, processing, report generation

**Invariant:** If before() succeeds, dependencies won't change before run() executes.

### run() - Main Processing

**Purpose:** Execute core logic. Return stats dict. **Stage controls its OWN iteration strategy.**

```python
def run(self, storage, checkpoint, logger):
    # CRITICAL: Always use get_remaining_pages for resume support
    remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

    for page_num in remaining:
        data = process_page(page_num)
        storage.stage(self.name).save_page(page_num, data, metrics=metrics)

    return {"pages_processed": len(remaining)}
```

**Key insight:** run() doesn't prescribe HOW to iterate. Different stages use different parallelization:
- **OCRStage:** ProcessPoolExecutor (CPU-bound Tesseract)
- **CorrectionStage:** ThreadPoolExecutor (I/O-bound LLM)
- **MergeStage:** ThreadPoolExecutor (deterministic)

Abstraction is: "Report to checkpoint after each page" - NOT "iterate in for loop."

### after() - Post-processing

**Purpose:** Validate outputs, generate quality reports.

```python
def after(self, storage, checkpoint, logger, stats):
    super().after(storage, checkpoint, logger, stats)  # Generates report.csv

    # Optional: Custom post-processing
    metadata = self._extract_metadata(storage)
    storage.update_metadata(metadata)
```

**Default:** Calls `generate_report()` to create CSV from checkpoint metrics filtered by report_schema.

## Schema-Driven Design

**Four schemas, four purposes:**

### 1. input_schema - What I Consume

Documents upstream data shape, enables validation when loading.

```python
class CorrectionStage(BaseStage):
    input_schema = OCRPageOutput  # "I read OCR outputs"
```

### 2. output_schema - What I Produce

Validates data BEFORE writing. Catches bugs early.

```python
storage.stage(self.name).save_page(
    page_num, data, schema=CorrectionPageOutput
)
```

### 3. checkpoint_schema - What I Track

Defines per-page metrics: costs, timing, tokens, quality indicators.

```python
class BasePageMetrics(BaseModel):
    page_num: int
    processing_time_seconds: float
    cost_usd: float

class LLMPageMetrics(BasePageMetrics):
    attempts: int
    tokens_total: int
    model_used: str
    # ... timing breakdown, usage details
```

**Minimum:** BasePageMetrics for all stages
**Extended:** LLMPageMetrics for LLM-based stages

### 4. report_schema - What I Report

Filters checkpoint metrics to quality-focused subset for CSV reports.

```python
class CorrectionPageReport(BaseModel):
    page_num: int
    total_corrections: int  # Quality metric
    avg_confidence: float   # Quality metric
    # Excludes: cost, tokens, timing (operational, not quality)
```

**Why separate?** Engineers need performance metrics (tokens/sec), domain experts need quality metrics (confidence).

### Validation at Boundaries

**Three critical points:**
1. **Reading dependencies:** `load_page(page_num, schema=input_schema)`
2. **Writing outputs:** `save_page(page_num, data, schema=output_schema)`
3. **Saving metrics:** `mark_completed(page_num, metrics={...})` validates against checkpoint_schema

**Invariant:** Page can only be marked complete if metrics validate.

## Runner Orchestration

**Location:** `infra/pipeline/runner.py`

```python
def run_stage(stage, storage, resume=False):
    # 1. Initialize infrastructure
    stage_storage = storage.stage(stage.name)
    checkpoint = stage_storage.checkpoint
    logger = create_logger(...)

    # 2. Execute lifecycle
    stage.before(storage, checkpoint, logger)
    stats = stage.run(storage, checkpoint, logger)
    stage.after(storage, checkpoint, logger, stats)

    # 3. Mark complete
    checkpoint.mark_stage_complete(metadata=stats)
```

**Infrastructure injection:** Each stage receives storage, checkpoint, logger (dependency injection pattern).

**Why inject?** Enables testing with mocks, runner controls logging/checkpointing globally, single source of truth.

## Stage Independence

**Stages communicate exclusively through files:**

```
OCR writes:    ocr/page_*.json (OCRPageOutput)
    ↓
Correction reads:  ocr/page_*.json, writes corrected/page_*.json
    ↓
Label reads:       ocr/page_*.json, writes labels/page_*.json
    ↓
Merge reads:       all three, writes merged/page_*.json
```

**Why file-based?**
- Durability (survives crashes)
- Auditability (inspect intermediate results)
- Parallelizable (separate processes/machines)
- Debuggable (reproduce with same files)
- Restartable (resume from exact point)

**Key invariant:** Stage can ONLY write to its own output directory.

### Testing in Isolation

```python
def test_correction_stage(tmp_path):
    # Create fake OCR outputs
    ocr_dir = tmp_path / "test-book" / "ocr"
    ocr_dir.mkdir(parents=True)
    (ocr_dir / "page_0001.json").write_text(fake_ocr.model_dump_json())

    # Run correction stage
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    stage = CorrectionStage(max_workers=1)
    run_stage(stage, storage)

    # Verify output
    corrected = storage.stage("corrected").load_page(1, schema=CorrectionPageOutput)
    assert corrected.page_number == 1
```

**Benefits:** Fast (no OCR), isolated (tests correction only), realistic (actual schemas).

## Key Design Invariants

1. **before() Success → Data Stability** - Dependencies won't change before run()
2. **All Writes Through Checkpoint** - Every save_page() updates checkpoint atomically
3. **Checkpoint is Source of Truth** - Page "done" if in checkpoint.page_metrics
4. **Metrics Match Schema** - All metrics validate against checkpoint_schema
5. **Stage Names Unique** - Name becomes directory, must be unique and filesafe
6. **Dependencies Acyclic** - No circular dependencies (DAG only)

## Cost & Telemetry

Every API call tracked:

```python
checkpoint.mark_completed(page_num=5, metrics={
    'cost_usd': 0.032,
    'tokens_total': 187,
    'model_used': 'anthropic/claude-sonnet-4',
    # ... full LLMPageMetrics
})
```

Enables: cost per book, resume cost estimation, stage comparison, optimization guidance.

## Summary: How It Works Together

```
User: shelf.py process {scan-id}
    ↓
For each stage:
    1. Load checkpoint
    2. before() - validate dependencies
    3. run() - process remaining pages
    4. after() - generate report
    5. mark_stage_complete()
    ↓
If interrupted:
    Re-run → checkpoint loads → get_remaining_pages() → resume from exact point
```

**This enables:**
- ✅ Independence - Stages evolve separately
- ✅ Resumability - No duplicate work
- ✅ Type safety - Catch corruption early
- ✅ Cost visibility - Track every API call
- ✅ Testability - Test in isolation
- ✅ Composability - Assemble declaratively
- ✅ Debuggability - Full audit trail

See also:
- `storage-system.md` - Three-tier storage
- `checkpoint-resume.md` - Resumption mechanisms
- `logging-metrics.md` - Observability
