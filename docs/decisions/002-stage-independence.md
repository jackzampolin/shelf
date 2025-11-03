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

**The learning loop:**
1. Try new approach in one stage
2. Run just that stage
3. Inspect output files
4. Iterate

If stages were coupled, this loop breaks. You'd need to:
- Understand other stage internals
- Worry about breaking other stages
- Run entire pipeline to test
- Debug across multiple stages

**Independence enables:**
- Change one stage without touching others
- Test stages in isolation
- Run stages independently during development
- Debug by inspecting files between stages

This is why we could evolve from initial experiments to current architecture - **loose coupling enabled learning**.

## The Four "-ables"

Stage independence makes each stage:

**1. Testable:**
- Mock filesystem, test stage logic
- No need to instantiate other stages
- Fast unit tests (no pipeline execution)

**2. Runnable:**
- `shelf.py book <id> run-stage ocr`
- Run one stage during development
- No need to run full pipeline

**3. Attributable:**
- Each stage records its own metrics
- Cost/time tracked per stage
- Clear ownership of outputs

**4. Debuggable:**
- Files between stages are inspection points
- Standard tools work (`cat`, `jq`, image viewers)
- Can see exactly what each stage produced

## Unix Philosophy Applied to Python

Small tools that:
- Do one thing well
- Compose through files
- Work together naturally

```
source → OCR → paragraph-correct → label-pages → extract-toc
        ↓     ↓                   ↓               ↓
      files files               files          files
```

Each arrow is the filesystem. Each stage is a tool.

## Implementation Pattern

**Read from dependencies:**
```python
# In paragraph_correct/storage.py
def load_ocr_page(self, storage: BookStorage, page_num: int):
    from pipeline.ocr.storage import OCRStageStorage
    ocr_storage = OCRStageStorage(stage_name='ocr')
    return ocr_storage.load_selected_page(storage, page_num)
```

**Declare dependencies:**
```python
# In paragraph_correct/__init__.py
class ParagraphCorrectStage(BaseStage):
    name = "paragraph-correct"
    dependencies = ["ocr", "source"]  # Explicit declaration
```

**Write to own directory:**
```python
# Each stage writes to storage.stage(self.name).output_dir
stage_storage = storage.stage("paragraph-correct")
stage_storage.save_page(page_num, corrected_data, schema=PageOutput)
```

**Check dependency status before running:**
```python
# In extract_toc/__init__.py run() method
from pipeline.paragraph_correct import ParagraphCorrectStage

para_correct_stage = ParagraphCorrectStage()
para_status = para_correct_stage.get_status(storage, logger)

if para_status["status"] != "completed":
    raise RuntimeError("paragraph-correct must complete before extract-toc")
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

**Enables rapid iteration:**
- Changed OCR from single-PSM → multi-PSM → vision-selection
- Removed entire stages (merged, build_structure)
- Added new stages (extract-toc)
- Never broke downstream stages

**Enables granular tracking:**
- Each stage has own metrics, logs, reports
- Can see cost/time breakdown per stage
- Clear attribution of errors

**Enables standards:**
- Each stage has own schemas (input/output contracts)
- Clear boundaries enforce discipline
- BaseStage interface provides consistency

**Enables debugging:**
- Inspect files between stages
- Run single stage repeatedly
- Compare outputs across iterations
- Use standard tools (no custom clients)

## What We Learned Through Iteration

The stage abstraction **emerged**, it wasn't designed upfront:
- Started simpler (fewer stages)
- Split stages when boundaries became clear
- Merged stages when separation added no value
- Removed stages when approach changed

**Independence made this evolution possible.** With tight coupling, we'd have ossified around the first design and missed better architectures.

## Alternatives Considered

**Shared state objects passed between stages:**
- Problem: All stages must run together
- Problem: Can't test in isolation
- Problem: Changes cascade across stages
- Rejected: Prevents rapid iteration

**Direct imports of other stage classes:**
```python
from pipeline.ocr import OCRStage  # DON'T DO THIS
ocr = OCRStage()
result = ocr.process(page)  # Tight coupling
```
- Problem: Stages become interdependent
- Problem: Changes break imports
- Problem: Can't evolve independently
- Rejected: Creates coupling we want to avoid

**Dependency injection container:**
- Problem: Adds complexity for no benefit
- Problem: Over-engineering at this scale
- Rejected: YAGNI (You Ain't Gonna Need It)

## The Real Benefit

Independence enables the **learning loop**:
- Experiment → Observe → Iterate → Improve

Fast iteration → More learning → Better architecture

**The stages you see today emerged through this process.** The independence property is what made that emergence possible.
