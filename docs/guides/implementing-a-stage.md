# Implementing a Pipeline Stage

A concise guide for building pipeline stages following established patterns.

## Directory Structure

```
pipeline/your-stage/
├── __init__.py          # BaseStage implementation
├── schemas/             # One schema per file
│   ├── __init__.py
│   ├── page_output.py
│   └── page_metrics.py
├── tools/               # Processing logic
│   └── processor.py
└── batch/               # (Optional) LLM batch processing
    ├── request_builder.py
    ├── result_handler.py
    ├── prompts.py
    └── schemas.py
```

## Stage Names Use Hyphens

**CRITICAL:** Stage names ALWAYS use hyphens: `ocr-pages`, `find-toc`, `extract-toc`

```python
# Correct
class OcrPagesStage(BaseStage):
    name = "ocr-pages"  # Uses hyphen

storage.stage("ocr-pages")  # Exact string match

# Wrong - causes lookup failures
name = "ocr_pages"  # Underscore breaks everything
```

**Exception:** Single-word stages don't need hyphens (`source`, but we removed `tesseract`)

## Reference Implementations

**Don't read this guide as your source of truth.** Read actual implementations:

- **Simple stage:** `pipeline/ocr_pages/` - Single LLM call per page
- **Complex stage:** `pipeline/label_pages/` - Multi-phase with batch processing
- **Non-LLM stage:** `pipeline/find_toc/` - Vision processing without LLM

When in doubt, copy the pattern from these stages.

## Core Principles

### 1. Ground Truth from Disk

Status and progress determined by checking files on disk, not in-memory state:

```python
def get_status(self, storage, logger):
    """Check disk to see what's actually done."""
    source_storage = storage.stage("source")
    stage_storage = storage.stage(self.name)

    # Count what exists on disk
    total_pages = len(source_storage.list_pages(extension="png"))
    completed = len(stage_storage.list_pages(extension="json"))

    return {
        "total_pages": total_pages,
        "remaining_pages": list(set(range(1, total_pages + 1)) - set(completed))
    }
```

**See:** `pipeline/ocr_pages/__init__.py:19-37`

### 2. If-Gates for Resume

Structure `run()` as if-gates that check progress and refresh:

```python
def run(self):
    progress = self.get_status(self.storage, self.logger)

    # Phase 1: Process pages
    if progress["remaining_pages"]:
        process_pages(progress["remaining_pages"])
        progress = self.get_status(self.storage, self.logger)  # Refresh

    # Phase 2: Generate report
    if not progress["artifacts"]["report_exists"]:
        generate_report()

    return {"status": "success"}
```

**See:** `pipeline/ocr_pages/__init__.py:39-57`

### 3. Incremental Metrics

Record metrics after each page via `MetricsManager`:

```python
stage_storage.save_page(
    page_num,
    page_data,
    schema=PageOutput
)

stage_storage.metrics_manager.record(
    key=f"page_{page_num:04d}",
    cost_usd=result.cost_usd,
    time_seconds=result.processing_time
)
```

**See:** `pipeline/ocr_pages/tools/processor.py:45-55`

### 4. Stage Independence

Communicate through files, not imports:

```python
# Correct - read from disk
def run(self):
    ocr_storage = self.storage.stage("ocr-pages")
    ocr_data = ocr_storage.load_page(page_num, schema=OcrPageOutput)

# Wrong - importing from other stages
from pipeline.ocr_pages.schemas import OcrPageOutput  # NO!
```

## Schemas: One Per File

```
schemas/
├── __init__.py           # Export all schemas
├── page_output.py        # What the stage produces
└── page_metrics.py       # Metrics for this page (optional)
```

**Always validate** when saving:

```python
stage_storage.save_page(
    page_num,
    data,
    schema=PageOutput  # Validates before saving
)
```

**See:** `pipeline/ocr_pages/schemas/page_output.py`

## LLM Batch Processing (Optional)

For stages that make LLM API calls, organize batch processing in `batch/`:

```
batch/
├── request_builder.py    # Build LLMRequest from page data
├── result_handler.py     # Process LLMResult and save
├── prompts.py           # System and user prompts
└── schemas.py           # LLM response schema
```

### Request Builder Pattern

```python
# batch/request_builder.py
from infra.llm.batch_client import LLMRequest
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import ResponseSchema

def prepare_request(page_num: int, storage, model: str):
    """Build LLM request for a page."""
    source_storage = storage.stage("source")
    image = source_storage.load_page(page_num)

    if not image:
        return None  # Skip this page

    return LLMRequest(
        id=f"page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(page_num)}
        ],
        images=[image],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "page_analysis",
                "strict": True,
                "schema": ResponseSchema.model_json_schema()
            }
        },
        metadata={"page_num": page_num}
    )
```

**See:** `pipeline/label_pages/batch/request_builder.py`

### Result Handler Pattern

```python
# batch/result_handler.py
from infra.llm.metrics import llm_result_to_metrics

def create_result_handler(storage, logger, output_schema):
    """Factory that creates handler with closure over dependencies."""

    def on_result(result):
        if result.success:
            page_num = result.request.metadata["page_num"]
            stage_storage = storage.stage("your-stage")

            # Validate and save
            validated = output_schema(**result.parsed_json)
            stage_storage.save_page(
                page_num,
                validated.model_dump(),
                schema=output_schema
            )

            # Record metrics
            metrics = llm_result_to_metrics(result, page_num)
            stage_storage.metrics_manager.record(
                key=f"page_{page_num:04d}",
                cost_usd=result.cost_usd or 0.0,
                time_seconds=metrics.processing_time_seconds,
                custom_metrics=metrics.model_dump()
            )

            logger.info(f"✓ Page {page_num} complete")
        else:
            page_num = result.request.metadata.get("page_num", "unknown")
            logger.error(f"✗ Page {page_num} failed: {result.error}")

    return on_result
```

**See:** `pipeline/label_pages/batch/result_handler.py`

### Using the Batch Processor

```python
# __init__.py
from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig
from infra.pipeline.batch_helpers import batch_process_with_preparation
from .batch.request_builder import prepare_request
from .batch.result_handler import create_result_handler

def run(self):
    progress = self.get_status(self.storage, self.logger)

    if not progress["remaining_pages"]:
        return {"status": "success"}

    # Configure processor
    config = LLMBatchConfig(
        model=self.model,
        max_workers=self.max_workers,
        max_retries=3
    )

    stage_storage = self.storage.stage(self.name)
    log_dir = stage_storage.output_dir / "logs"

    processor = LLMBatchProcessor(
        checkpoint=stage_storage.metrics_manager,
        logger=self.logger,
        log_dir=log_dir,
        config=config
    )

    # Create handler
    handler = create_result_handler(
        storage=self.storage,
        logger=self.logger,
        output_schema=PageOutput
    )

    # Process batch
    batch_process_with_preparation(
        stage_name=self.name,
        pages=progress["remaining_pages"],
        request_builder=prepare_request,
        result_handler=handler,
        processor=processor,
        logger=self.logger,
        storage=self.storage,
        model=self.model
    )

    return {"status": "success"}
```

**See:** `pipeline/label_pages/__init__.py`

## Common Mistakes

### ❌ Don't Put Business Logic in `__init__.py`

```python
# Wrong - processing logic in stage file
class YourStage(BaseStage):
    def run(self):
        for page in pages:
            result = self.process_page(page)  # Business logic here

    def process_page(self, page):
        # Lots of processing code...
```

```python
# Correct - delegate to tools/
class YourStage(BaseStage):
    def run(self):
        from .tools.processor import process_batch
        process_batch(self.storage, self.logger, pages)
```

### ❌ Don't Use Underscores in Stage Names

```python
# Wrong - causes "Page not found" errors
class OcrPagesStage(BaseStage):
    name = "ocr_pages"  # Breaks storage.stage() lookup

# Correct
class OcrPagesStage(BaseStage):
    name = "ocr-pages"  # Matches directory: pipeline/ocr_pages/
```

### ❌ Don't Skip Schema Validation

```python
# Wrong - no validation
stage_storage.save_file(f"page_{page_num:04d}.json", data)

# Correct - validates structure
stage_storage.save_page(page_num, data, schema=PageOutput)
```

### ❌ Don't Batch Metrics Updates

```python
# Wrong - lose resume capability
results = []
for page in pages:
    results.append(process_page(page))
# Save all at end - if it crashes, all progress lost!

# Correct - record immediately
for page in pages:
    result = process_page(page)
    stage_storage.save_page(page, result, schema=PageOutput)
    metrics_manager.record(key=f"page_{page:04d}", ...)
```

## Testing

**DO NOT run stages yourself.** These cost money via OpenRouter API calls.

The user will run stages when ready:

```bash
# User commands
uv run python shelf.py book <scan-id> run-stage your-stage
uv run python shelf.py book <scan-id> run-stage your-stage --workers 20
```

## Stage Registration

Add your stage to `infra/pipeline/registry.py`:

```python
STAGE_DEFINITIONS = [
    {'name': 'ocr-pages', 'class': 'pipeline.ocr_pages.OcrPagesStage'},
    {'name': 'your-stage', 'class': 'pipeline.your_stage.YourStage'},  # Add here
    # ...
]
```

**See:** `infra/pipeline/registry.py:1-7`

## Summary

1. **Read reference implementations first:** `pipeline/ocr_pages/` or `pipeline/label_pages/`
2. **Stage names use hyphens:** `ocr-pages` not `ocr_pages`
3. **Ground truth from disk:** Check files, not memory
4. **If-gates for resume:** Check progress, refresh, continue
5. **Incremental metrics:** Record after each page
6. **Stage independence:** Read from disk, don't import other stages
7. **One schema per file:** Easy to find and modify
8. **LLM stages:** Use `batch/` pattern with request builder + result handler

When in doubt, copy the pattern from `pipeline/ocr_pages/` or `pipeline/label_pages/`.
