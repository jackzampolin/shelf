# 2. Stage Independence (Communicate Through Files)

**Date:** 2025-10-30

**Status:** Accepted

## Context

This project has gone through many iterations. We've learned a lot about OCR on books: what matters, what doesn't, what scales, what breaks. The stage abstraction emerged through co-development over many cycles of experimentation and refinement.

Pipeline stages need to pass data between each other. How they communicate determines how rapidly we can iterate and learn.

## Decision

**Stages communicate only through files. No imports of processing logic between stages.**

Each stage:
- Reads from dependency stage output directories
- Writes to its own output directory
- Declares dependencies explicitly
- **MAY import dependency stages to check status** (ground truth from disk)
- NEVER imports to call processing logic

Dependencies flow through the filesystem, not through Python method calls.

## Why Independence Enables Rapid Iteration

**The learning loop:** Try approach → Run stage → Inspect files → Iterate

If coupled: must understand all stages, run entire pipeline, debug across boundaries.

If independent: change one, test alone, inspect outputs, iterate fast.

**Loose coupling enabled learning** - we evolved from simple to current architecture.

## The Four "-ables"

Independence makes stages:
1. **Testable:** Mock filesystem, no other stage instantiation
2. **Runnable:** `shelf.py book <id> run-stage ocr` works alone
3. **Attributable:** Each stage owns its metrics/logs/outputs
4. **Debuggable:** Files = inspection points, standard tools work

## Unix Philosophy Applied to Python

Small tools that:
- Do one thing well
- Compose through files
- Work together naturally

```
source → tesseract → ocr-pages → label-pages → find-toc → extract-toc
        ↓           ↓            ↓              ↓          ↓
      files       files        files          files      files
```

Each arrow is the filesystem. Each stage is a tool.

## Implementation Pattern

**Read from dependencies:**
```python
# In label_pages/storage.py
def load_ocr_page(self, storage: BookStorage, page_num: int):
    from pipeline.ocr_pages.storage import OcrPagesStorage
    ocr_storage = OcrPagesStorage(stage_name='ocr-pages')
    return ocr_storage.load_page(storage, page_num)
```

**Declare dependencies:**
```python
# In label_pages/__init__.py
class LabelPagesStage(BaseStage):
    name = "label-pages"
    dependencies = ["ocr-pages", "source"]  # Explicit declaration
```

**Write to own directory:**
```python
# Each stage writes to storage.stage(self.name).output_dir
stage_storage = storage.stage("label-pages")
stage_storage.save_page(page_num, labeled_data, schema=PageOutput)
```

**Check dependency status before running:**
```python
# In extract_toc/__init__.py run() method
from pipeline.label_pages import LabelPagesStage

label_stage = LabelPagesStage()
label_status = label_stage.get_status(storage, logger)

if label_status["status"] != "completed":
    raise RuntimeError("label-pages must complete before extract-toc")
```

This pattern ties to **ADR 001 (Ground Truth from Disk)**:
- Status check reads file existence, not processing logic
- Import the stage class, call `get_status()`, check disk state
- Never call processing methods like `run()` or `process_page()`
- Status is a pure function of what files exist

**The distinction:**
- ✅ Import to check status (reads disk) - OK
- ❌ Import to call processing (executes logic) - NOT OK

## Consequences

**Enabled evolution:** Single-PSM → multi-PSM → vision-selection OCR. Removed stages (merged, build_structure). Added stages (extract-toc). Never broke downstream.

**Enables:** Granular tracking (metrics/logs/reports per stage), clear standards (schemas, BaseStage interface), easy debugging (inspect files, standard tools).

## Alternatives Considered

- **Shared state objects:** Can't test/run in isolation. Rejected.
- **Direct stage imports:** (`ocr = OCRStage(); ocr.process()`) Creates coupling. Rejected.
- **Dependency injection:** Over-engineering. Rejected (YAGNI).

## Core Principle

Independence enables the learning loop: Experiment → Observe → Iterate → Improve.

**The stages you see today emerged through iteration.** Tight coupling would have ossified the first design.
