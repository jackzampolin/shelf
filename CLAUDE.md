# Development Guide

Concise principles for building the book scanning pipeline. Code is truth, this is context.

## Values

**Clean Codebase Principles:**
1. **One schema per file** - Easy to find, easy to modify
2. **Ground truth from disk** - Files are reality, not checkpoint state
3. **Explicit over implicit** - All phases visible in run()
4. **Self-contained modules** - Clear ownership boundaries
5. **Resume anywhere** - Incremental checkpoints, if-gate pattern

**The OCR Stage is the Reference Implementation.**
Read `pipeline/ocr/` and `docs/guides/implementing-a-stage.md` to understand the pattern.

---

## Stage Implementation Pattern

### Directory Structure
```
pipeline/your_stage/
├── __init__.py          # Stage class ONLY (no business logic)
├── status.py            # Progress tracking (ground truth from disk)
├── storage.py           # Stage-specific file I/O
├── schemas/             # One schema per file
│   ├── page_output.py
│   ├── page_metrics.py
│   └── page_report.py
├── tools/               # Helper functions
└── llm_calls/           # Per-LLM-call organization (optional)
```

### Lifecycle Hooks
```python
class YourStage(BaseStage):
    def get_progress(self, storage, checkpoint, logger):
        """Calculate what work remains (delegate to status tracker)."""
        return self.status_tracker.get_progress(...)

    def before(self, storage, checkpoint, logger):
        """Validate dependencies exist."""
        pass

    def run(self, storage, checkpoint, logger):
        """Execute all phases with if-gates for resume."""
        progress = self.get_progress(storage, checkpoint, logger)

        # Phase 1: Main processing
        if needs_phase_1(progress):
            do_phase_1()
            progress = self.get_progress(...)  # Refresh

        # Phase 2: Report generation
        if needs_phase_2(progress):
            generate_report()

        # Mark complete
        if all_done(progress):
            checkpoint.set_phase("completed")

        return {"pages_processed": ...}
```

### Key Patterns

**1. If-gates for resume:**
```python
def run(self, storage, checkpoint, logger):
    progress = self.get_progress(...)

    if progress["remaining_pages"]:
        # Process remaining pages
        progress = self.get_progress(...)  # Refresh after each phase

    if not progress["artifacts"]["report_exists"]:
        # Generate report
```

**2. Ground truth from disk:**
```python
# status.py checks files on disk
def get_progress(self, storage, checkpoint, logger):
    completed = [p for p in pages if output_file_exists(p)]
    remaining = [p for p in pages if p not in completed]
    return {"remaining_pages": remaining, ...}
```

**3. Incremental checkpoints:**
```python
for page_num in remaining_pages:
    result = process_page(page_num)
    storage.stage(self.name).save_page(page_num, result, schema=self.output_schema)
    checkpoint.mark_completed(page_num, cost_usd=0.1, metrics={...})
```

---

## Schema Organization

**Always one schema per file:**

```python
# schemas/page_output.py
class YourPageOutput(BaseModel):
    page_number: int
    content: str

# schemas/page_metrics.py
class YourPageMetrics(BaseModel):
    page_num: int
    cost_usd: float
    processing_time_seconds: float

# schemas/page_report.py (quality metrics only)
class YourPageReport(BaseModel):
    page_num: int
    quality_score: float
```

**Why:** Easy to find schemas, clear ownership, prevents bloat.

---

## Git Workflow

**Work progression:**
```
Issue → Branch → Code → Test → Commit → PR → Merge
```

**Commit conventions:**
```bash
git commit -m "feat: add parallel provider selection"
git commit -m "fix: handle empty OCR outputs"
git commit -m "docs: update stage implementation guide"
git commit -m "refactor: split schemas into separate files"
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

---

## Cost Awareness

**CRITICAL: Pipeline costs real money (OpenRouter API).**

**ALWAYS ask before running:**
- `shelf.py process <scan-id>` - Costs money
- `shelf.py sweep <stage>` - Costs money per book
- Any LLM-based stage (correction, labels, merge)

**Safe to run:**
- `shelf.py list` - Free
- `shelf.py status <scan-id>` - Free
- `pytest tests/` - Free
- Reading code, grepping, analyzing - Free

---

## Prompt Engineering

**Core principles:**
1. **Teach concepts, not patterns** - Never reference specific test books
2. **XML tags for structure** - `<role>`, `<task>`, `<output_schema>`
3. **Vision-first** - Examine images before text analysis
4. **Self-verification** - Model checks own work before returning
5. **Generalize** - Works on books we haven't seen

**Example:**
```python
❌ "Extract 'Chapter 1: Title' format from The Accidental President"
✅ "Remove chapter number prefix (Roman/Arabic/'Chapter X') from titles"
```

---

## Project Architecture

**Pipeline:**
```
PDF → Split Pages → OCR → Correction → Label → Merge → Structure
```

**OCR Stage** (reference implementation):
- Multi-phase: OCR → Agreement → Auto-select → Vision → Metadata → Report
- Parallel provider execution (PSM 3/4/6)
- Vision-based selection for low-agreement pages
- Self-contained: `__init__.py`, `status.py`, `storage.py`, `schemas/`, `tools/`, `vision/`

**Infrastructure:**
- `BaseStage` - Lifecycle: `before()` → `get_progress()` → `run()`
- `BookStorage` - File I/O with schema validation
- `CheckpointManager` - Resume from any interruption
- `PipelineLogger` - Structured logging with metrics

**Library:**
- Storage root: `~/Documents/book_scans/`
- Each book: `<scan-id>/` (e.g., `modest-lovelace/`)
- Each stage: `<scan-id>/<stage>/` (e.g., `modest-lovelace/ocr/`)

---

## Quick Reference

**Environment:**
```bash
uv venv && source .venv/bin/activate
uv pip install -e .
uv run python shelf.py list
```

**Testing:**
```bash
uv run python -m pytest tests/ -v
```

**CLI:**
```bash
shelf.py shelve <pdf>           # Add book to library
shelf.py list                   # List all books
shelf.py status <scan-id>       # Check progress
shelf.py process <scan-id>      # Run full pipeline
shelf.py clean <scan-id> --stage ocr  # Reset stage
```

---

## Documentation Hierarchy

1. **Code** - Ultimate source of truth
2. **docs/guides/implementing-a-stage.md** - How to build stages
3. **pipeline/ocr/** - Reference implementation
4. **README.md** - Quick start and usage
5. **CLAUDE.md** (this file) - Development principles

---

## Remember

**Clean code:**
- One schema per file
- Ground truth from disk
- Explicit phases in run()
- If-gates for resume

**Safe operations:**
- Test before committing
- Ask before spending money
- Update docs with code
- Reference OCR for patterns

**When stuck:**
Read `pipeline/ocr/` - it shows the pattern.
