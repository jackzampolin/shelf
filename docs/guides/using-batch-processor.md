# Using the LLM Batch Processor

## Overview

The `LLMBatchProcessor` provides a clean, reusable interface for batch LLM operations. It handles:
- Parallel request preparation (with progress tracking)
- LLM execution with retries
- Progress bars with token/cost metrics
- Result callbacks

You provide three components:
1. **Request builder** - Loads data and builds LLM requests (prompts inside)
2. **Result handler** - Processes LLM responses
3. **Schema** - Validates LLM output structure

## The Interface

### 1. Configure the Processor

```python
from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig

config = LLMBatchConfig(
    model="x-ai/grok-4-fast",
    max_workers=10,
    max_retries=3,
)

processor = LLMBatchProcessor(
    checkpoint=checkpoint,
    logger=logger,
    log_dir=Path("label-pages/logs"),
    config=config,
)
```

### 2. Build the Three Components

#### Component 1: Request Builder (loads data + prompts)

```python
from infra.llm.batch_client import LLMRequest
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import ResponseSchema

def prepare_request(
    page_num: int,
    storage: BookStorage,
    model: str,
    total_pages: int,
) -> Optional[LLMRequest]:
    """
    Request builder: Load data and construct LLM request.

    Responsibilities:
    - Load images, OCR data, or other inputs
    - Build prompts from templates
    - Construct LLMRequest with response schema

    Returns None if page cannot be processed.
    """
    # Load data
    image = load_image(storage, page_num)
    ocr_data = load_ocr(storage, page_num)

    if not image or not ocr_data:
        return None

    # Build prompts (prompts live here!)
    user_prompt = build_user_prompt(
        ocr_text=ocr_data.text,
        page_num=page_num,
        total_pages=total_pages,
    )

    # Construct request with schema
    response_schema = {
        "type": "json_schema",
        "json_schema": {
            "name": "page_analysis",
            "strict": True,
            "schema": ResponseSchema.model_json_schema()
        }
    }

    return LLMRequest(
        id=f"page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt}
        ],
        images=[image],
        response_format=response_schema,
        metadata={"page_num": page_num},
    )
```

#### Component 2: Result Handler (processes responses)

```python
from infra.llm.batch_client import LLMResult
from infra.llm.metrics import llm_result_to_metrics

def create_result_handler(storage, stage_storage, checkpoint, logger, output_schema):
    """
    Result handler factory: Process LLM responses.

    Responsibilities:
    - Extract data from LLMResult
    - Validate with output schema
    - Save to disk
    - Update checkpoint
    """
    def on_result(result: LLMResult):
        if result.success:
            page_num = result.request.metadata['page_num']

            # Extract and validate
            data = result.parsed_json
            validated = output_schema(**data)

            # Save output
            stage_storage.save_page(
                storage=storage,
                page_num=page_num,
                data=validated.model_dump(),
                schema=output_schema,
                cost_usd=result.cost_usd or 0.0,
                metrics=llm_result_to_metrics(result, page_num).model_dump(),
            )

            logger.info(f"✓ Page {page_num} complete")
        else:
            page_num = result.request.metadata.get('page_num', 'unknown')
            logger.error(f"✗ Page {page_num} failed", error=result.error)

    return on_result
```

#### Component 3: Schema (validates structure)

```python
from pydantic import BaseModel, Field
from typing import List

class BlockClassification(BaseModel):
    """Individual block classification."""
    block_id: int
    classification: str
    confidence: float = Field(ge=0.0, le=1.0)

class ResponseSchema(BaseModel):
    """LLM response schema - what the model returns."""
    blocks: List[BlockClassification] = Field(
        ...,
        description="Block classifications"
    )
```

### 3. Execute the Batch

```python
from infra.llm.batch_processor import batch_process_with_preparation

stats = batch_process_with_preparation(
    stage_name="Vision Analysis",
    pages=remaining_pages,
    request_builder=prepare_request,    # Component 1
    result_handler=handler,              # Component 2
    processor=processor,
    logger=logger,
    # Additional kwargs passed to request_builder
    storage=storage,
    model=config.model,
    total_pages=total_pages,
)

# stats contains: completed, failed, total_cost_usd, total_tokens, elapsed_seconds
```

## File Structure Recommendations

### Option 1: Single-Stage Pattern (Recommended for simple cases)

**Best for:** Stages with one LLM call per page

```
pipeline/your_stage/
├── __init__.py              # Stage orchestration
├── status.py                # Progress tracking
├── storage.py               # File I/O operations
├── schemas/
│   ├── page_output.py       # Final output schema
│   └── page_metrics.py      # Metrics schema
└── vision/                  # LLM processing
    ├── request_builder.py   # Component 1: prepare_request()
    ├── result_handler.py    # Component 2: create_result_handler()
    ├── prompts.py          # Prompt templates
    └── schemas.py          # Component 3: ResponseSchema
```

**Rationale:**
- ✅ Flat structure - easy to navigate
- ✅ Clear separation: request building → prompts → handling
- ✅ All LLM code in `vision/` directory
- ✅ Scales well for single-stage workflows

**Example usage in __init__.py:**
```python
from .vision.request_builder import prepare_request
from .vision.result_handler import create_result_handler
from .vision.schemas import ResponseSchema

processor = LLMBatchProcessor(checkpoint, logger, log_dir, config=config)
handler = create_result_handler(storage, stage_storage, checkpoint, logger, output_schema)

batch_process_with_preparation(
    stage_name="Your Stage",
    pages=remaining_pages,
    request_builder=prepare_request,
    result_handler=handler,
    processor=processor,
    logger=logger,
    storage=storage,
    model=self.model,
)
```

---

### Option 2: Multi-Stage Pattern (Recommended for sequential stages)

**Best for:** Stages with multiple sequential LLM calls (Stage 1 → Stage 2)

```
pipeline/your_stage/
├── __init__.py
├── status.py
├── storage.py
├── schemas/
│   ├── page_output.py           # Final output (merged stages)
│   └── page_metrics.py
├── stage1/                       # Stage 1 processing
│   ├── request_builder.py       # prepare_stage1_request()
│   ├── result_handler.py        # create_stage1_handler()
│   ├── prompts.py               # Stage 1 prompts
│   └── schemas.py               # Stage1Response (LLM output)
└── stage2/                       # Stage 2 processing
    ├── request_builder.py       # prepare_stage2_request()
    ├── result_handler.py        # create_stage2_handler()
    ├── prompts.py               # Stage 2 prompts
    └── schemas.py               # Stage2Response (LLM output)
```

**Rationale:**
- ✅ **Crystal clear** - Each stage in its own folder
- ✅ **Self-contained** - All Stage 1 code in `stage1/`, all Stage 2 code in `stage2/`
- ✅ **Consistent** - Same structure as Option 1, just repeated per stage
- ✅ **Scalable** - Easy to add `stage3/` if needed

**Example usage:**
```python
from .stage1.request_builder import prepare_stage1_request
from .stage1.result_handler import create_stage1_handler
from .stage2.request_builder import prepare_stage2_request
from .stage2.result_handler import create_stage2_handler

# Stage 1: Structural analysis
processor_s1 = LLMBatchProcessor(checkpoint, logger, log_dir_s1, config=config)
handler_s1 = create_stage1_handler(storage, stage_storage, checkpoint, logger)

batch_process_with_preparation(
    stage_name="Stage 1",
    pages=stage1_remaining,
    request_builder=prepare_stage1_request,
    result_handler=handler_s1,
    processor=processor_s1,
    logger=logger,
    storage=storage,
    model=config.model,
)

# Stage 2: Block classification (uses Stage 1 results)
processor_s2 = LLMBatchProcessor(checkpoint, logger, log_dir_s2, config=config)
handler_s2 = create_stage2_handler(storage, stage_storage, checkpoint, logger, output_schema)

batch_process_with_preparation(
    stage_name="Stage 2",
    pages=stage2_remaining,
    request_builder=prepare_stage2_request,
    result_handler=handler_s2,
    processor=processor_s2,
    logger=logger,
    storage=storage,
    model=config.model,
)
```

---

### Option 3: Component-Based (Alternative for multi-stage)

**Best for:** Many stages, prefer grouping by component type

```
pipeline/your_stage/
├── __init__.py
├── status.py
├── storage.py
├── schemas/
│   ├── page_output.py
│   └── page_metrics.py
└── vision/
    ├── request_builders/
    │   ├── stage1.py
    │   └── stage2.py
    ├── result_handlers/
    │   ├── stage1.py
    │   └── stage2.py
    ├── prompts/
    │   ├── stage1.py
    │   └── stage2.py
    └── schemas/
        ├── stage1_response.py
        └── stage2_response.py
```

**Rationale:**
- ✅ Consistent component grouping
- ✅ Easy to find all request builders, all handlers, etc.
- ❌ More directories to navigate
- ❌ More imports in __init__.py

---

## File Structure Comparison

| Pattern | Pros | Cons | Best For |
|---------|------|------|----------|
| **Option 1: Single-Stage** | ✅ Simple, flat<br>✅ Easy to navigate<br>✅ Quick to scaffold | ❌ Doesn't scale to multi-stage | Single LLM call per page |
| **Option 2: Multi-Stage** | ✅ Crystal clear (stage1/, stage2/)<br>✅ Self-contained stages<br>✅ Same structure as Option 1<br>✅ Easy to add stage3/ | ❌ More folders | Sequential stages (Stage 1→2→3) |
| **Option 3: Component-Based** | ✅ Consistent grouping | ❌ More directories to navigate<br>❌ More imports needed | Many stages (4+), but rare |

**Recommendation:**
- **Start with Option 1** (`vision/` folder) for single-stage workflows
- **Migrate to Option 2** (`stage1/`, `stage2/` folders) when adding sequential stages
- **Avoid Option 3** unless you have 4+ stages (very rare)

**Key insight:** Option 2 is just Option 1 repeated - each stage gets its own self-contained folder with the same structure.

---

## Minimal Example

Here's a complete minimal stage using the batch processor:

```python
# pipeline/example_stage/__init__.py
from infra.llm.batch_processor import LLMBatchProcessor, LLMBatchConfig, batch_process_with_preparation
from .vision.request_builder import prepare_request  # or .stage1.request_builder for multi-stage
from .vision.result_handler import create_result_handler
from .schemas.page_output import ExamplePageOutput

class ExampleStage(BaseStage):
    def run(self, storage, checkpoint, logger):
        progress = self.get_progress(storage, checkpoint, logger)
        remaining_pages = progress["remaining_pages"]

        if not remaining_pages:
            logger.info("No pages to process")
            return

        # Configure processor
        config = LLMBatchConfig(model=self.model, max_workers=self.max_workers)
        log_dir = storage.stage(self.stage_name).output_dir / "logs"
        processor = LLMBatchProcessor(checkpoint, logger, log_dir, config=config)

        # Create handler
        handler = create_result_handler(
            storage=storage,
            checkpoint=checkpoint,
            logger=logger,
            output_schema=ExamplePageOutput,
        )

        # Process batch
        batch_process_with_preparation(
            stage_name=self.stage_name,
            pages=remaining_pages,
            request_builder=prepare_request,
            result_handler=handler,
            processor=processor,
            logger=logger,
            storage=storage,
            model=self.model,
        )
```

```python
# pipeline/example_stage/vision/request_builder.py
from infra.llm.batch_client import LLMRequest
from .prompts import SYSTEM_PROMPT, build_user_prompt
from .schemas import ExampleResponse

def prepare_request(page_num, storage, model):
    image = storage.stage('source').load_page(page_num)

    return LLMRequest(
        id=f"page_{page_num:04d}",
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(page_num)}
        ],
        images=[image],
        response_format={"type": "json_schema", "json_schema": {...}},
        metadata={"page_num": page_num},
    )
```

```python
# pipeline/example_stage/vision/result_handler.py
def create_result_handler(storage, checkpoint, logger, output_schema):
    def on_result(result):
        if result.success:
            page_num = result.request.metadata['page_num']
            validated = output_schema(**result.parsed_json)
            storage.stage('example').save_page(page_num, validated.model_dump())
            logger.info(f"✓ Page {page_num}")
    return on_result
```

---

## Key Patterns

### 1. Request Builders Return None for Skipped Pages

```python
def prepare_request(page_num, storage, model):
    if should_skip_page(page_num):
        return None  # Skip this page

    return LLMRequest(...)
```

### 2. Request Builders Can Return Extra Data

```python
def prepare_request(page_num, storage, model):
    ocr_page = load_ocr(storage, page_num)
    request = LLMRequest(...)

    return (request, ocr_page)  # Extra data passed to handler via metadata
```

### 3. Handlers Access Metadata

```python
def on_result(result):
    page_num = result.request.metadata['page_num']
    extra_data = result.request.metadata.get('extra_data')  # From tuple return
```

### 4. Use Factories for Handler Closures

```python
def create_result_handler(storage, checkpoint, logger):
    """Factory that captures dependencies in closure."""
    def on_result(result):
        # Has access to storage, checkpoint, logger
        page_num = result.request.metadata['page_num']
        storage.save_page(page_num, result.parsed_json)
        checkpoint.mark_completed(page_num)
    return on_result
```

---

## Common Mistakes

❌ **Don't pass max_workers to batch_process_with_preparation()**
```python
# Wrong
batch_process_with_preparation(..., max_workers=10)  # Not needed!

# Right
config = LLMBatchConfig(max_workers=10)
processor = LLMBatchProcessor(..., config=config)
batch_process_with_preparation(..., processor=processor)  # Uses config.max_workers
```

❌ **Don't forget to handle None returns**
```python
# Wrong
def prepare_request(page_num, storage, model):
    image = load_image(storage, page_num)
    return LLMRequest(...)  # Crashes if image is None!

# Right
def prepare_request(page_num, storage, model):
    image = load_image(storage, page_num)
    if not image:
        return None  # Skip this page
    return LLMRequest(...)
```

❌ **Don't access result.metadata directly**
```python
# Wrong
page_num = result.metadata['page_num']  # AttributeError!

# Right
page_num = result.request.metadata['page_num']  # Access via result.request
```

---

## Summary

**The 3-Component Interface:**
1. **Request Builder** - Loads data, builds prompts, creates LLMRequest
2. **Result Handler** - Processes LLMResult, saves outputs, updates checkpoint
3. **Schema** - Validates LLM response structure (Pydantic model)

**File Structure:**
- Simple: Use **Option 1** (flat structure)
- Multi-stage: Use **Option 2** (stage separation)

**Key principle:** Request builders encapsulate prompts and data loading. Handlers encapsulate persistence and validation. Processor handles execution and progress tracking.
