# Logging, Metrics, and Reporting Architecture

## Purpose

Dual-output logging, structured metrics collection, and quality-focused reporting for debugging, cost tracking, and quality analysis across pipeline stages.

## Three-Layer Observability

1. **PipelineLogger** - Dual-output structured logging (JSON + human-readable)
2. **Metrics Schemas** - Type-safe metrics collection per page
3. **Report Generation** - Quality-focused CSV reports

## PipelineLogger Design

**Location:** `infra/pipeline/logger.py`

### Dual Output Strategy

| Format | Purpose | Consumer | Location |
|--------|---------|----------|----------|
| **JSON (JSONL)** | Programmatic analysis | Scripts, monitoring | `{stage_dir}/logs/{stage}_{timestamp}.jsonl` |
| **Human-readable** | Real-time feedback | Terminal operators | Console output |

**Why separate?** Machine logs stay structured, human logs optimized for readability. If console fails, JSON continues.

### Context Propagation

**Two types:**

1. **Base context** (automatic): `scan_id`, `stage`
2. **Dynamic context** (updates):
   - Permanent: `set_context(worker_id=3)`
   - Scoped: `with logger.context_scope(page=42): ...`

**Thread safety:** `_context_lock` protects modifications during parallel processing.

### Logging Methods

**Standard levels:**
```python
logger.debug/info/warning/error/critical("Message", key=value)
```

**Specialized methods:**
```python
logger.progress("Correcting pages", current=42, total=447, cost_usd=1.23)
logger.cost("Batch complete", cost_usd=0.32)
logger.page_event("Corrected", page=42, corrections=15)
logger.page_error("Failed", page=42, error="Invalid JSON")
logger.start_stage() / logger.complete_stage(duration_seconds=120.5)
```

**Design principle:** Method signatures document what to log.

## Metrics Schemas

**Location:** `infra/pipeline/schemas.py` (base) + `pipeline/*/schemas.py` (stage-specific)

### BasePageMetrics - Minimum Contract

```python
class BasePageMetrics(BaseModel):
    page_num: int
    processing_time_seconds: float
    cost_usd: float  # Even if 0.0
```

**Purpose:** Cross-stage analysis of costs, timing, resource utilization.

### LLMPageMetrics - Vision/LLM Extension

```python
class LLMPageMetrics(BasePageMetrics):
    attempts: int                  # Retry tracking
    tokens_total: int             # Output tokens
    tokens_per_second: float      # Throughput
    model_used: str               # Which model
    provider: str                 # anthropic, openai, etc.

    # Timing breakdown
    queue_time_seconds: float     # Wait before execution
    execution_time_seconds: float # Actual LLM time
    total_time_seconds: float     # Queue + execution
    ttft_seconds: Optional[float] # Time to first token

    usage: Dict[str, Any]         # Raw provider data
```

**Why detailed timing?** Reveals bottlenecks:
- High `queue_time` → rate limiter too aggressive or insufficient workers
- High `execution_time` → model struggling or network latency
- High `ttft` → slow generation start, not queue problem

### Checkpoint vs Report Schemas

**checkpoint_schema** - ALL operational metrics (full fidelity)

```python
class CorrectionPageMetrics(LLMPageMetrics):
    # Operational (kept):
    cost_usd, tokens_total, queue_time_seconds, attempts

    # Quality (also kept):
    total_corrections, avg_confidence, text_similarity_ratio
```

**report_schema** - Quality-focused subset

```python
class CorrectionPageReport(BaseModel):
    # Quality only:
    page_num, total_corrections, avg_confidence, text_similarity_ratio

    # Excluded: cost, tokens, timing (operational, not quality)
```

**Why separate?**

| Audience | Needs | Schema |
|----------|-------|--------|
| Engineers | Performance debugging | checkpoint_schema |
| Domain experts | Quality assessment | report_schema |

## Report Generation

**Location:** `infra/pipeline/base_stage.py:generate_report()`

### Data Flow

```
Stage processing
    ↓
Collect per-page metrics
    ↓
Save to checkpoint (checkpoint_schema)
    ↓
Stage completes
    ↓
after() hook calls generate_report()
    ↓
Extract report_schema fields from page_metrics
    ↓
Write to report.csv
```

### Implementation

```python
def generate_report(self, storage, logger):
    # 1. Get all metrics from checkpoint
    all_metrics = checkpoint.get_all_metrics()

    # 2. Use report_schema if defined, else checkpoint_schema
    schema = self.report_schema or self.checkpoint_schema

    # 3. Extract and validate
    report_rows = []
    for page_num, metrics in all_metrics.items():
        report = schema(**metrics)
        report_rows.append(report.model_dump())

    # 4. Write CSV
    report_file = storage.stage(self.name).output_dir / 'report.csv'
    # ... write with csv.DictWriter
```

### CSV Format

**Example: corrected/report.csv**

```csv
page_num,total_corrections,avg_confidence,text_similarity_ratio,characters_changed
1,15,0.92,0.88,73
2,8,0.95,0.94,42
3,23,0.85,0.78,156
```

**Analysis capabilities:**
- Sort by confidence to find low-quality pages
- Filter by similarity to find major rewrites
- Import to Excel/pandas for deeper analysis

## Integration: How It Flows Together

### Page Processing with Metrics

```python
# In CorrectionStage.run()
for page_num in checkpoint.get_remaining_pages(total_pages):
    # Log progress
    logger.progress("Correcting pages", current=page_num, total=total_pages)

    # Process with LLM
    result = llm_client.process_page(page_num)

    # Collect full metrics
    metrics = {
        # Operational:
        'page_num': page_num,
        'cost_usd': result.cost_usd,
        'processing_time_seconds': result.total_time_seconds,
        'tokens_total': result.usage['completion_tokens'],

        # Quality:
        'total_corrections': 15,
        'avg_confidence': 0.92
    }

    # Save atomically (data + checkpoint)
    storage.stage(self.name).save_page(page_num, result.data, metrics=metrics)

    # Log completion
    logger.page_event(f"Corrected page {page_num}", page=page_num)
```

### Metrics Flow Summary

```
LLMBatchClient (usage, timing, cost)
    ↓
Stage.run() (adds domain metrics)
    ↓
checkpoint.mark_completed(metrics={...})
    ↓
.checkpoint file (JSON - full checkpoint_schema)
    ↓
[Stage completes]
    ↓
BaseStage.after() → generate_report()
    ↓
report.csv (filtered to report_schema)
```

## Progressive Logging During Parallel Processing

### LLMBatchClient Event Integration

```python
class LLMEvent(Enum):
    QUEUED = "queued"
    EXECUTING = "executing"
    STREAMING = "streaming"       # Throttled updates
    FIRST_TOKEN = "first_token"   # TTFT measurement
    COMPLETED = "completed"
    FAILED = "failed"
    PROGRESS = "progress"         # Batch-level
```

**Usage in stage:**

```python
def on_event(event: EventData):
    if event.event_type == LLMEvent.PROGRESS:
        logger.progress(
            "Batch processing",
            current=event.completed,
            total=event.total_requests,
            cost_usd=event.total_cost_usd
        )

batch_client.process_batch(requests, on_event=on_event)
```

**Console output:**
```
ℹ️ [10:23:45] [correction] Batch processing
    [████████████░░░░░░░░░░░░░░░░] 42.5% (17/40) ($0.1234)
```

## Cost Awareness

Every `mark_completed()` stores `cost_usd`:

```python
checkpoint.mark_completed(page_num=42, cost_usd=0.032, metrics={...})
```

**Aggregation:**
```python
summary = checkpoint.get_metrics_summary()
# Returns: {'cost_usd': {'sum': 2.34, 'avg': 0.023, 'p50': 0.02, 'p95': 0.06}}
```

**Financial logging:**
```python
logger.cost("Checkpoint saved", cost_usd=0.023)
# JSON: {"timestamp": "...", "cost_usd": 0.023, ...}
```

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **JSON + Human formats** | Dual optimization for machines and operators |
| **Thread-safe context** | Workers logging simultaneously |
| **checkpoint vs report schemas** | Separate operational from quality metrics |
| **Per-stage log files** | Prevents bloat, enables per-stage analysis |
| **CSV reports** | Actionable for humans, sortable, importable |
| **Detailed timing breakdown** | Diagnose bottlenecks |
| **Cost in every metric** | Financial tracking at operation level |

## Observability Hierarchy

```
Terminal (Human)
    ↑
PipelineLogger (dual output)
    ↑
{stage}_{timestamp}.jsonl (Machine)
    ↑
checkpoint.mark_completed(metrics)
    ↑
.checkpoint (Source of Truth)
    ↑
generate_report()
    ↑
report.csv (Quality Analysis)
```

## Summary

The logging, metrics, and reporting system provides:

1. **Dual output** - Machine-parseable + human-readable
2. **Structured metrics** - Type-safe via Pydantic schemas
3. **Quality focus** - Report schema filters operational noise
4. **Cost tracking** - Every API call tracked financially
5. **Progressive feedback** - Real-time updates during batch processing
6. **Thread safety** - Context protected for concurrent access
7. **Analysis-ready** - CSV reports for quality review

**Key insight:** Separating concerns (logging vs metrics vs reports) and audiences (engineers vs domain experts) provides real-time visibility for operators, debugging capability for engineers, quality analysis for domain experts, and financial tracking for budget planning.

See also:
- `stage-abstraction.md` - How stages use logging/metrics
- `checkpoint-resume.md` - How metrics enable resumption
- `storage-system.md` - Where logs and reports are stored
