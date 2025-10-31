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
- `shelf.py list`, `shelf.py status <scan-id>`, `shelf.py show <scan-id>`
- `pytest tests/` - Run tests
- Reading files, grepping, analyzing code

**Testing protocol:**
1. Propose changes and explain reasoning
2. User tests on sample pages first
3. Never start expensive sweeps without approval
4. Never assume "test it" means "run a $50 operation"

**Always check costs:** `shelf.py status <scan-id>` tracks spending per stage.
</critical_instructions>

---

<git_workflow>
## Git Workflow

**Source of truth:**
- Current state: Main branch only
- History: Git commits
- Planning: GitHub issues/projects
- Never: Keep old versions, drafts, outdated docs

**Work progression:**
```
Issue → Branch → Code → Test → Doc → Commit → PR → Merge
```

**Every piece of work should:**
1. Start with a GitHub issue
2. Happen on a feature branch
3. Include tests
4. Update relevant docs
5. Use atomic commits (logical chunks)
6. Go through PR review

### Branching Strategy

```bash
# Always from main
git checkout main
git pull
git checkout -b <type>/<description>

# Types: feature/, fix/, docs/, refactor/
```

### Commit Conventions

```bash
git commit -m "<type>: <present-tense-description>"

# Types: feat, fix, docs, refactor, test, chore
```

**Examples:**
- `feat: add quote extraction for biographies`
- `fix: handle empty source documents`
- `docs: update setup instructions`
- `test: add tests for metadata tracking`

### Pull Requests

When creating PRs:
1. Link to the issue: "Fixes #123"
2. Describe what changed and why
3. Confirm tests pass
4. Confirm docs updated

### Issue Organization

**Every issue should have:**
- Clear title
- Labels: `development`, `documentation`, `bug`, `enhancement`, `research`
- Assignment to project board
- Milestone if applicable

</git_workflow>

---

<stage_implementation_pattern>
## Stage Implementation Pattern

**OCR is the reference implementation.**
Read `pipeline/ocr/` and `docs/guides/implementing-a-stage.md` to understand the pattern.

### Core Principles

**Clean Codebase Values:**
1. **One schema per file** - Easy to find, easy to modify
2. **Ground truth from disk** - Files are reality, not checkpoint state
3. **Explicit over implicit** - All phases visible in run()
4. **Self-contained modules** - Clear ownership boundaries
5. **Resume anywhere** - Incremental checkpoints, if-gate pattern

### Directory Structure

```
pipeline/your_stage/
├── __init__.py          # Stage class + BaseStage methods ONLY
├── status.py            # Progress tracking (ground truth from disk)
├── storage.py           # Stage-specific storage operations
├── schemas/             # One schema per file
│   ├── page_output.py
│   ├── page_metrics.py
│   └── page_report.py
├── tools/               # Helper functions and workers
└── llm_calls/           # Per-LLM-call organization (if needed)
```

### BaseStage Lifecycle

Every stage MUST extend `BaseStage`:

```python
class YourStage(BaseStage):
    name = "your_stage"
    dependencies = ["prev_stage"]

    output_schema = YourPageOutput
    checkpoint_schema = YourPageMetrics
    report_schema = YourPageReport

    def get_progress(self, storage, checkpoint, logger):
        # Delegate to status tracker
        return self.status_tracker.get_progress(...)

    def before(self, storage, checkpoint, logger):
        # Validate dependencies exist
        pass

    def run(self, storage, checkpoint, logger):
        progress = self.get_progress(storage, checkpoint, logger)

        # Phase 1: Main processing (if-gate for resume)
        if progress["remaining_pages"]:
            process_pages()
            progress = self.get_progress(...)  # Refresh

        # Phase 2: Report generation
        if not progress["artifacts"]["report_exists"]:
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

    if needs_phase_1(progress):
        do_phase_1()
        progress = self.get_progress(...)  # Refresh

    if needs_phase_2(progress):
        do_phase_2()

    if all_done(progress):
        checkpoint.set_phase("completed")
```

**2. Ground truth from disk:**
```python
def get_progress(self, storage, checkpoint, logger):
    # Check files on disk (ground truth), not checkpoint state
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

### Stage Independence

Stages communicate exclusively through files, never direct imports:

```python
# ✅ Correct: File-based dependency
ocr_data = storage.stage('ocr').load_page(page_num, schema=OCRPageOutput)

# ✗ Wrong: Direct import creates coupling
from pipeline.ocr import OCRStage
```

**Why:** Enables testing stages in isolation, modifying stages independently.

</stage_implementation_pattern>

---

<schema_validation>
## Schema Validation

**Three schemas, three purposes:**

1. **output_schema** - Validates data BEFORE writing to disk
2. **checkpoint_schema** - Validates metrics BEFORE marking complete
3. **report_schema** - Filters quality metrics for CSV reports

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

# schemas/page_report.py
class YourPageReport(BaseModel):
    page_num: int
    quality_score: float
```

**Why:** Easy to find schemas, clear ownership, prevents bloat.

**Always pass schemas to storage operations:**

```python
# Validate on save
storage.stage(self.name).save_page(page_num, data, schema=self.output_schema)

# Validate on load
data = storage.stage('prev').load_page(page_num, schema=PrevPageOutput)
```

**Never:** Skip schema validation or write raw JSON without Pydantic models.

</schema_validation>

---

<testing_discipline>
## Testing Discipline

**Before any commit:**

```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run specific modules
uv run python -m pytest tests/infra/ -v
uv run python -m pytest tests/tools/ -v
```

**Test philosophy:**
- Minimal but functional - test behavior, not implementation
- Use `tmp_path` fixtures for isolation
- No external dependencies required
- Fast tests (< 1s for full suite)

**Test stages in isolation with mock data:**

```python
def test_my_stage(tmp_path):
    # Setup: Create fake dependency outputs
    book_dir = tmp_path / "test-book"
    (book_dir / "prev_stage").mkdir(parents=True)

    fake_data = PrevPageOutput(page_number=1, ...)
    (book_dir / "prev_stage" / "page_0001.json").write_text(
        fake_data.model_dump_json()
    )

    # Run: Execute stage
    storage = BookStorage(scan_id="test-book", storage_root=tmp_path)
    stage = MyStage(max_workers=1)
    stats = run_stage(stage, storage)

    # Assert: Verify outputs
    output = storage.stage("my_stage").load_page(1, schema=MyPageOutput)
    assert output.page_number == 1
```

</testing_discipline>

---

<infrastructure_apis>
## Infrastructure APIs

### Storage API

```python
# Access any stage's data
storage.stage('ocr').load_page(5, schema=OCRPageOutput)
storage.stage(self.name).save_page(5, data, schema=self.output_schema)
```

### Checkpoint API

```python
# Get pages to process (resume-aware)
remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

# Mark complete atomically
checkpoint.mark_completed(page_num, cost_usd=0.032, metrics={...})
```

### Logger API

```python
logger.info("Processing", page=42)
logger.progress("Correcting pages", current=42, total=447, cost_usd=1.23)
logger.page_error("Failed", page=42, error=str(e))
```

**Never:**
- Construct file paths manually
- Write checkpoint files directly
- Use print() instead of logger

</infrastructure_apis>

---

<prompt_engineering>
## Prompt Engineering Principles

**Core rule: Teach concepts that generalize, never reference test data.**

### Structure and Format

**Use XML tags for semantic organization:**
- `<role>`, `<task>`, `<output_schema>` - Clear section boundaries
- Put critical instructions at START and END (primacy/recency effect)
- Vision-first workflow: Examine images before text analysis

**Example structure:**

```python
"""<role>You are a [role]. Your job is [purpose].</role>

<critical_instructions>
Most important constraint/rule here (primacy effect)
</critical_instructions>

<task>Main instructions...</task>

<output_requirements>
Critical output rules here (recency effect)
</output_requirements>"""
```

### Avoid Overfitting

**NEVER reference specific test books:**

```python
❌ "Book: 'The Accidental President' has 5 Parts..."
✅ "PATTERN: Parts-based structure (5-10 divisions, 'Part [I-X]:' prefix)"
```

**Teach concepts, not patterns:**

```python
❌ "Extract 'Chapter 1: Title' format"
✅ "Remove chapter number prefix (works for Roman, Arabic, 'Chapter X', etc.)"
```

### Design Patterns That Work

1. **Two-stage for complexity:** Stage 1 observes (no reasoning), Stage 2 extracts
2. **Self-verification checklists:** Model checks own work before returning
3. **Vision-first:** Examine images for structure, use text for accuracy
4. **Philosophy over rules:** Teach WHAT/WHY, then HOW
5. **Handle failure modes:** Explicit "if not found" instructions

### Quick Test

Before finalizing a prompt, ask:
1. Does it reference specific books from test data? (Remove them)
2. Does it teach a concept or memorize a pattern? (Teach concepts)
3. Would it work on a book I haven't seen? (Test generalization)

**Remember:** Building for all books, not just current test cases.

</prompt_engineering>

---

<parallelization>
## Parallelization Strategy

| Work Type | Executor | Workers | Example |
|-----------|----------|---------|---------|
| CPU-bound | `ProcessPoolExecutor` | `cpu_count()` | OCR (Tesseract) |
| I/O-bound (LLM) | `ThreadPoolExecutor` | `Config.max_workers` | Correction, Label |
| Deterministic | `ThreadPoolExecutor` | Fixed (8) | Merge |

**Never:** Use ProcessPoolExecutor for LLM calls (pickling overhead) or ThreadPoolExecutor for CPU-heavy work (GIL contention).

</parallelization>

---

<documentation_hygiene>
## Documentation Hygiene

**When code changes:**
1. Update relevant docs immediately
2. Never create "v2" docs - update in place
3. Remove outdated sections
4. Keep examples current

**Documentation hierarchy:**
1. Code itself - The ultimate source of truth
2. `docs/guides/implementing-a-stage.md` - Implementation guide
3. `pipeline/ocr/` - Reference implementation
4. `README.md` - Quick start, basic usage
5. `CLAUDE.md` (this file) - Timeless workflow principles

</documentation_hygiene>

---

<environment_setup>
## Environment Setup

### Python Virtual Environment

```bash
# First-time setup
uv venv
source .venv/bin/activate
uv pip install -e .

# Running commands
uv run python shelf.py <command>
uv run python -m pytest tests/
```

### Secrets Management

```bash
cp .env.example .env
# Edit .env with actual values
# .env is in .gitignore
```

**Required environment variables:**
- `OPENROUTER_API_KEY` - For LLM API calls
- `BOOK_STORAGE_ROOT` (optional) - Defaults to `~/Documents/book_scans`

</environment_setup>

---

<project_architecture>
## Project Architecture

### Pipeline

```
PDF → Split Pages → OCR → Correction → Label → Merge → Structure (TBD)
```

**Pipeline properties:**
- Each stage inherits from `BaseStage`
- Three-hook lifecycle: `before()` → `run()` → `after()`
- Schema-driven validation at all boundaries
- Automatic resume from checkpoints
- Cost tracking for every LLM API call
- Quality reports generated in `after()` hook

### OCR Stage (Reference Implementation)

**Multi-phase processing:**
- Phase 1: Parallel provider execution (PSM 3/4/6)
- Phase 2a: Calculate provider agreement
- Phase 2b: Auto-select high-agreement pages (>= 0.95)
- Phase 2c: Vision-based selection for low-agreement pages
- Phase 3: Metadata extraction (page ranges, chapter detection)
- Phase 4: Report generation

**Self-contained modules:**
- `__init__.py` - Stage class with if-gates
- `status.py` - Ground truth progress tracking
- `storage.py` - File I/O operations
- `schemas/` - 10 schemas, one per file
- `tools/` - Helper functions and workers
- `vision/` - Vision-based selection logic

### Key Concepts

- **Library:** `~/Documents/book_scans/` - filesystem is source of truth
- **Library Metadata:** `.library.json` - operational state (shuffle orders)
- **Scan ID:** Random Docker-style name (e.g., "modest-lovelace")
- **Checkpointing:** `.checkpoint` file per stage, `page_metrics` is source of truth
- **Schemas:** Input/output/checkpoint/report enforce type safety
- **Storage tiers:** Library → BookStorage → StageStorage → CheckpointManager

### CLI Commands

```bash
# Library management
shelf.py shelve <pdf>
shelf.py list
shelf.py delete <scan-id>

# Single book operations
shelf.py process <scan-id>
shelf.py process <scan-id> --stage ocr
shelf.py status <scan-id>
shelf.py clean <scan-id> --stage ocr

# Library-wide sweeps (EXPENSIVE - always ask first!)
shelf.py sweep labels
shelf.py sweep labels --reshuffle
shelf.py sweep reports
```

### Current State

- ✅ Infrastructure - BaseStage, storage, checkpoint, logging
- ✅ OCR Stage - Tesseract + vision selection
- ✅ Correction Stage - Vision-based error correction
- ✅ Label Stage - Page numbers and block classification
- ✅ Merge Stage - Three-way deterministic merge
- ❌ Structure Stage - Not yet implemented

</project_architecture>

---

<quick_decision_guide>
## Quick Decision Guide

**Starting work?**
- Check issues first
- Create branch from main: `git checkout -b <type>/<description>`
- Run `tree -L 2 --gitignore` to see structure

**Making changes?**
- Test locally first: `pytest tests/ -v`
- Commit logical chunks: `git commit -m "feat: description"`
- Update docs immediately (no "v2" docs, update in place)

**Stuck or unsure?**
- Check OCR stage for patterns: `pipeline/ocr/`
- Read implementation guide: `docs/guides/implementing-a-stage.md`
- Look at git history: `git log --oneline`
- Review similar PRs on GitHub

**Ready to merge?**
- Tests passing: `pytest tests/ -v`
- Docs updated
- PR created with "Fixes #123"
- PR approved

</quick_decision_guide>

---

<remember>
## Remember

**Critical reminders - check these every time:**

### 1. COST AWARENESS
- ALWAYS ask before running expensive operations
- Test on samples, not full books
- Check costs: `shelf.py status <scan-id>`
- Never start sweeps without approval

### 2. GIT WORKFLOW
- One source of truth: main branch
- Issue → Branch → Code → Test → Doc → Commit → PR → Merge
- Commit conventions: `<type>: <description>` (feat/fix/docs/refactor/test/chore)
- Atomic commits (logical chunks)

### 3. STAGE IMPLEMENTATION
- **OCR is the reference pattern** - read `pipeline/ocr/` when stuck
- One schema per file
- Ground truth from disk (not checkpoint state)
- If-gates for resume support
- Incremental checkpoints (mark_completed after each page)

### 4. TESTING
- Test everything before commit: `pytest tests/ -v`
- No untested code
- Fast tests (< 1s for full suite)
- Test stages in isolation with mock data

### 5. SCHEMAS
- Three schemas: output, checkpoint, report
- Always validate: pass schema to save_page/load_page
- Never skip validation

### 6. PROMPTS
- Teach concepts that generalize, never reference test data
- XML tags for structure: `<role>`, `<critical_instructions>`, `<task>`
- Primacy/recency: critical info at START and END
- Vision-first workflow

### 7. DOCUMENTATION
- Update with code changes (not after)
- No "v2" docs - update in place
- Code is source of truth

**When stuck:** Read `pipeline/ocr/` - it shows the modern pattern.

</remember>

---

*This workflow ensures consistent, trackable progress. All work flows through GitHub issues and PRs, creating a complete audit trail.*
