# AI Assistant Workflow Guide

<critical_instructions>
## COST AWARENESS - READ THIS FIRST

**This pipeline costs real money via OpenRouter API calls.**

NEVER run these operations without explicit user approval:
- `shelf.py process <scan-id>` - Full pipeline processing
- `shelf.py process <scan-id> --stage <stage>` - Single stage processing
- `shelf.py sweep <stage>` - Library-wide stage processing
- Any command that spawns LLM API calls (correction, labels, merge, structure)

Safe operations (can run freely):
- `shelf.py list`, `shelf.py status <scan-id>`, `pytest tests/`
- Reading files, grepping, analyzing code

**Always ask first. Test on samples, not full books.**
</critical_instructions>

---

<git_workflow>
## Git Workflow

**Work progression:**
```
Issue → Branch → Code → Test → Doc → Commit → PR → Merge
```

**Branching:**
```bash
git checkout main && git pull
git checkout -b <type>/<description>
# Types: feature/, fix/, docs/, refactor/
```

**Commits:**
```bash
git commit -m "<type>: <present-tense-description>"
# Types: feat, fix, docs, refactor, test, chore
```

**PRs:**
- Link issue: "Fixes #123"
- Confirm tests pass
- Confirm docs updated
</git_workflow>

---

<stage_implementation>
## Stage Implementation

**OCR is the reference implementation.**
Read `pipeline/ocr/` and `docs/guides/implementing-a-stage.md` for full details.

**Core principles:**
1. **One schema per file** - Easy to find, easy to modify
2. **Ground truth from disk** - Files are reality, not checkpoint state
3. **If-gates for resume** - Each phase checks progress, refreshes, continues
4. **Incremental checkpoints** - `mark_completed()` after each page
5. **Stage independence** - Communicate through files, not imports

**Structure:**
```
pipeline/your_stage/
├── __init__.py       # BaseStage implementation only
├── status.py         # Progress from disk (ground truth)
├── storage.py        # File I/O operations
├── schemas/          # One schema per file
└── tools/            # Workers and helpers
```

**Key pattern (if-gates):**
```python
def run(self, storage, checkpoint, logger):
    progress = self.get_progress(...)

    if progress["remaining_pages"]:
        process_pages()
        progress = self.get_progress(...)  # Refresh

    if not progress["artifacts"]["report_exists"]:
        generate_report()

    if all_done(progress):
        checkpoint.set_phase("completed")
```
</stage_implementation>

---

<schemas>
## Schemas

**Three schemas, three purposes:**
1. **output_schema** - Validates data before writing to disk
2. **checkpoint_schema** - Validates metrics before marking complete
3. **report_schema** - Filters quality metrics for CSV reports

**Always one schema per file in `schemas/`.**

Always pass schemas to storage:
```python
storage.stage(self.name).save_page(page_num, data, schema=self.output_schema)
data = storage.stage('prev').load_page(page_num, schema=PrevPageOutput)
```
</schemas>

---

<testing>
## Testing

**Before any commit:**
```bash
uv run python -m pytest tests/ -v
```

**Test philosophy:**
- Minimal but functional - test behavior, not implementation
- Use `tmp_path` fixtures for isolation
- Fast tests (< 1s for full suite)
</testing>

---

<infrastructure>
## Infrastructure APIs

**Storage:**
```python
storage.stage('ocr').load_page(5, schema=OCRPageOutput)
storage.stage(self.name).save_page(5, data, schema=self.output_schema)
```

**Checkpoint:**
```python
remaining = checkpoint.get_remaining_pages(total_pages, resume=True)
checkpoint.mark_completed(page_num, cost_usd=0.032, metrics={...})
```

**Logger:**
```python
logger.info("Processing", page=42)
logger.progress("Correcting", current=42, total=447, cost_usd=1.23)
logger.page_error("Failed", page=42, error=str(e))
```

**Never:** Construct paths manually, write checkpoints directly, use print().
</infrastructure>

---

<prompts>
## Prompt Engineering

**Core rule: Teach concepts that generalize, never reference test data.**

**Use XML tags for structure:**
```python
"""<role>You are X. Your job is Y.</role>

<critical_instructions>
Most important constraint (primacy effect)
</critical_instructions>

<task>Main instructions...</task>

<output_requirements>
Critical output rules (recency effect)
</output_requirements>"""
```

**Avoid overfitting:**
- ❌ "Extract 'Chapter 1: Title' from The Accidental President"
- ✅ "Remove chapter number prefix (Roman, Arabic, 'Chapter X')"

**Design patterns:**
1. Two-stage for complexity (observe → extract)
2. Self-verification checklists
3. Vision-first workflow
4. Philosophy over rules (teach WHAT/WHY, then HOW)
5. Handle failure modes explicitly

**Before finalizing:** Does it reference test data? Would it work on unseen books?
</prompts>

---

<parallelization>
## Parallelization

| Work Type | Executor | Workers | Example |
|-----------|----------|---------|---------|
| CPU-bound | `ProcessPoolExecutor` | `cpu_count()` | OCR (Tesseract) |
| I/O-bound (LLM) | `ThreadPoolExecutor` | `Config.max_workers` | Correction, Label |
| Deterministic | `ThreadPoolExecutor` | Fixed (8) | Merge |
</parallelization>

---

<docs>
## Documentation

**When code changes:**
1. Update docs immediately (not after)
2. Never create "v2" docs - update in place
3. Remove outdated sections

**Hierarchy:**
1. Code itself - source of truth
2. `docs/guides/implementing-a-stage.md` - implementation guide
3. `pipeline/ocr/` - reference implementation
4. `README.md` - quick start
5. `CLAUDE.md` (this file) - timeless principles
</docs>

---

<architecture>
## Project Architecture

**Pipeline:**
```
PDF → Split → OCR → Correction → Label → Merge → Structure (TBD)
```

**OCR Stage (reference implementation):**
- Multi-phase: OCR → Agreement → Auto-select → Vision → Metadata → Report
- Self-contained: `__init__.py`, `status.py`, `storage.py`, `schemas/`, `tools/`, `vision/`
- If-gates for resume at any phase

**Key concepts:**
- **Library:** `~/Documents/book_scans/` - filesystem is source of truth
- **Scan ID:** Random Docker name (e.g., "modest-lovelace")
- **Checkpointing:** `.checkpoint` per stage, `page_metrics` is ground truth
- **Storage tiers:** Library → BookStorage → StageStorage → CheckpointManager

**CLI:**
```bash
shelf.py shelve <pdf>           # Add book
shelf.py list                   # List books
shelf.py status <scan-id>       # Check progress/costs
shelf.py process <scan-id>      # Run pipeline (EXPENSIVE - ask first!)
shelf.py clean <scan-id> --stage ocr  # Reset stage
```

**Current state:**
- ✅ Infrastructure, OCR, Correction, Label, Merge
- ❌ Structure stage (not yet implemented)
</architecture>

---

<environment>
## Environment Setup

```bash
# First-time setup
uv venv && source .venv/bin/activate
uv pip install -e .

# Running commands
uv run python shelf.py <command>
uv run python -m pytest tests/
```

**Secrets (.env):**
- `OPENROUTER_API_KEY` - For LLM API calls
- `BOOK_STORAGE_ROOT` (optional) - Defaults to `~/Documents/book_scans`
</environment>

---

<remember>
## Remember - Critical Checklist

**1. COST AWARENESS**
- ALWAYS ask before running expensive operations
- Test on samples, not full books
- Check costs: `shelf.py status <scan-id>`

**2. GIT WORKFLOW**
- One source of truth: main branch
- Issue → Branch → Code → Test → Doc → Commit → PR
- Commit format: `<type>: <description>` (feat/fix/docs/refactor/test/chore)

**3. STAGE IMPLEMENTATION**
- **OCR is the reference** - read `pipeline/ocr/` when stuck
- One schema per file
- Ground truth from disk (not checkpoint state)
- If-gates for resume (check progress, refresh, continue)
- Incremental checkpoints (`mark_completed` after each page)

**4. TESTING**
- Test before commit: `pytest tests/ -v`
- No untested code
- Fast tests (< 1s full suite)

**5. SCHEMAS**
- Three schemas: output, checkpoint, report
- Always validate: pass schema to `save_page`/`load_page`
- Never skip validation

**6. PROMPTS**
- Teach concepts that generalize, never reference test data
- XML tags: `<role>`, `<critical_instructions>`, `<task>`, `<output_requirements>`
- Primacy/recency: critical info at START and END
- Vision-first workflow

**7. DOCUMENTATION**
- Update with code changes (not after)
- No "v2" docs - update in place
- Code is source of truth

**When stuck:** Read `pipeline/ocr/` - it shows the modern pattern.
</remember>

---

*All work flows through GitHub issues and PRs, creating a complete audit trail.*
