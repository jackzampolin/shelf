# AI Assistant Workflow Guide

## Core Workflow Principles

### Git as Source of Truth
- **Current state:** Lives on main branch only
- **History:** Lives in git commits
- **Planning:** Lives in GitHub issues/projects
- **Never:** Keep old versions, drafts, or outdated docs

### Work Progression
```
Issue → Branch → Code → Test → Doc → Commit → PR → Merge
```

Every piece of work should:
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

---

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

---

## Documentation Hygiene

**When code changes:**
1. Update relevant docs immediately
2. Never create "v2" docs - update in place
3. Remove outdated sections
4. Keep examples current

**Documentation hierarchy:**
- `README.md` - Quick start, basic usage, current status
- `CLAUDE.md` (this file) - Timeless workflow principles
- `docs/` - Additional documentation and planning notes
- Code itself - The ultimate source of truth

---

## Environment Setup

### Python Virtual Environment

This project uses `uv` for Python package management:

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

Never commit secrets:
```bash
cp .env.example .env
# Edit .env with actual values
# .env is in .gitignore
```

**Required environment variables:**
- `OPENROUTER_API_KEY` - For LLM API calls
- `BOOK_STORAGE_ROOT` (optional) - Defaults to `~/Documents/book_scans`

---

## GitHub Organization

### Issue Creation
Every issue should have:
- Clear title
- Labels (minimum: `development`, `documentation`, `bug`, or `enhancement`)
- Assignment to project board
- Milestone if applicable

### Issue Labels
Core labels:
- `development` - Code work
- `documentation` - Docs updates
- `bug` - Something broken
- `enhancement` - Improvements
- `research` - Research tasks

---

## Quick Decision Guide

**Starting work?**
- Check issues first
- Create branch from main
- Run `tree -L 2 --gitignore` to see structure

**Making changes?**
- Test locally first
- Commit logical chunks
- Update docs immediately

**Stuck or unsure?**
- Check existing patterns
- Look at git history
- Review similar PRs

**Ready to merge?**
- Tests passing
- Docs updated
- PR approved
- Linked issue closed

---

## Stage Abstraction Principles

When implementing or modifying pipeline stages, follow these core principles:

### Always Use BaseStage for New Stages

Every stage MUST extend `BaseStage` (`infra/pipeline/base_stage.py`):

```python
class MyStage(BaseStage):
    name = "my_stage"           # Output directory name
    dependencies = ["prev_stage"]  # Required upstream stages

    output_schema = MyPageOutput        # What you write
    checkpoint_schema = MyPageMetrics   # What you track
    report_schema = MyPageReport        # What you report (optional)
```

**Never:** Create stages that don't inherit from BaseStage or bypass the lifecycle hooks.

### Schema Validation is Mandatory

**Three schemas, three purposes:**

1. **output_schema** - Validates data BEFORE writing to disk
2. **checkpoint_schema** - Validates metrics BEFORE marking complete
3. **report_schema** - Filters quality metrics for CSV reports (optional but recommended for LLM stages)

Always pass schemas to storage operations:

```python
# Validate on save
storage.stage(self.name).save_page(page_num, data, schema=self.output_schema)

# Validate on load
data = storage.stage('prev').load_page(page_num, schema=PrevPageOutput)
```

**Never:** Skip schema validation or write raw JSON without Pydantic models.

### Use Provided Storage/Logger/Checkpoint APIs

**Storage API** (`BookStorage`, `StageStorage`):

```python
# Access any stage's data
storage.stage('ocr').load_page(5, schema=OCRPageOutput)
storage.stage(self.name).save_page(5, data, metrics=metrics)
```

**Checkpoint API** (`CheckpointManager`):

```python
# Get pages to process (resume-aware)
remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

# Mark complete atomically
checkpoint.mark_completed(page_num, cost_usd=0.032, metrics={...})
```

**Logger API** (`PipelineLogger`):

```python
logger.info("Processing", page=42)
logger.progress("Correcting pages", current=42, total=447, cost_usd=1.23)
logger.page_error("Failed", page=42, error=str(e))
```

**Never:**
- Construct file paths manually (`f"{book_dir}/{stage}/page_{num}.json"`)
- Write checkpoint files directly
- Use print() instead of logger

### Implement Resume Support via get_remaining_pages

**Always** use `checkpoint.get_remaining_pages(resume=True)` in `run()`:

```python
def run(self, storage, checkpoint, logger):
    total_pages = len(storage.stage('source').list_output_pages(extension='png'))
    remaining = checkpoint.get_remaining_pages(total_pages, resume=True)

    for page_num in remaining:
        # Process only incomplete pages
        pass
```

**Why:** Enables cost-saving resume from exact interruption point. Never reprocess completed pages.

**Never:** Iterate over all pages without checking checkpoint.

### Report Quality Metrics in after() Hook

**Default behavior** (usually sufficient):

```python
def after(self, storage, checkpoint, logger, stats):
    super().after(storage, checkpoint, logger, stats)  # Generates report.csv
```

**Override for custom post-processing:**

```python
def after(self, storage, checkpoint, logger, stats):
    # ALWAYS call parent first to generate report.csv
    super().after(storage, checkpoint, logger, stats)

    # Then add custom logic
    metadata = self._extract_metadata(storage)
    storage.update_metadata(metadata)
```

**Never:** Skip calling `super().after()` if you override - reports won't generate.

### Choose Appropriate Parallelization

| Work Type | Executor | Workers | Example |
|-----------|----------|---------|---------|
| CPU-bound | `ProcessPoolExecutor` | `cpu_count()` | OCR (Tesseract) |
| I/O-bound (LLM) | `ThreadPoolExecutor` | `Config.max_workers` | Correction, Label |
| Deterministic | `ThreadPoolExecutor` | Fixed (8) | Merge |

**Never:** Use ProcessPoolExecutor for LLM calls (pickling overhead) or ThreadPoolExecutor for CPU-heavy work (GIL contention).

### Stage Independence

Stages communicate exclusively through files, never direct imports:

```python
# ✅ Correct: File-based dependency
ocr_data = storage.stage('ocr').load_page(page_num, schema=OCRPageOutput)

# ✗ Wrong: Direct import creates coupling
from pipeline.ocr import OCRStage
ocr_stage = OCRStage()
ocr_data = ocr_stage.process(...)
```

**Why:** Enables testing stages in isolation, modifying stages independently, and running stages in different processes.

### Testing Stages

**Always test stages in isolation with mock data:**

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

---

## Project-Specific Notes

### Architecture
Book processing pipeline using BaseStage abstraction:

```
PDF → Split Pages → OCR → Correction → Label → Merge → Structure (TBD)
```

**Pipeline properties:**
- Each stage inherits from `BaseStage` (`infra/pipeline/base_stage.py`)
- Three-hook lifecycle: `before()` → `run()` → `after()`
- Schema-driven validation at all boundaries
- Automatic resume from checkpoints (no manual state management)
- Cost tracking for every LLM API call
- Quality reports generated in `after()` hook

### Key Concepts
- **Library:** `~/Documents/book_scans/` - filesystem is source of truth for books
- **Library Metadata:** `.library.json` - operational state (shuffle orders for sweeps)
- **Scan ID:** Random Docker-style name (e.g., "modest-lovelace")
- **Checkpointing:** `.checkpoint` file per stage, `page_metrics` is source of truth
- **Schemas:** Input/output/checkpoint/report enforce type safety
- **Storage tiers:** Library → BookStorage → StageStorage → CheckpointManager

### CLI Usage
All commands use `uv run python shelf.py <command>`. See `README.md` for reference.

**Library management:**
- `shelf.py shelve <pdf>` - Shelve books into library
- `shelf.py list` - List all books
- `shelf.py delete <scan-id>` - Delete book

**Single book operations:**
- `shelf.py process <scan-id>` - Run full pipeline (auto-resumes)
- `shelf.py process <scan-id> --stage ocr` - Run single stage
- `shelf.py status <scan-id>` - Check progress and costs
- `shelf.py clean <scan-id> --stage ocr` - Reset stage to start fresh

**Library-wide sweeps:**
- `shelf.py sweep labels` - Run stage across all books (persistent random order)
- `shelf.py sweep labels --reshuffle` - Create new random order
- `shelf.py sweep reports` - Regenerate reports from checkpoints

### Cost Awareness
This pipeline costs money (OpenRouter API). Be mindful:
- Don't re-run stages unnecessarily (check status first)
- Test prompts on small samples before full runs
- Use checkpoints to resume interrupted runs (saves money)
- Check `shelf.py status <scan-id>` for cost tracking
- Reports show cost per page in checkpoint metrics

### Current State
- ✅ Infrastructure (`infra/`) - BaseStage, storage, checkpoint, logging complete
- ✅ OCR Stage - Tesseract extraction with metadata
- ✅ Correction Stage - Vision-based error correction
- ✅ Label Stage - Page numbers and block classification
- ✅ Merge Stage - Three-way deterministic merge
- ❌ Structure Stage - Not yet implemented

**For implementation details, see:**
- `README.md` - Usage and current status
- `docs/architecture/` - Stage abstraction, storage, checkpoint, logging design
- `docs/guides/implementing-a-stage.md` - Step-by-step guide for new stages
- Code itself - The source of truth

---

## Remember

1. **One source of truth** - Main branch is reality
2. **Issues before code** - Plan in GitHub
3. **Test everything** - No untested code
4. **Commit often** - Logical, atomic chunks
5. **Docs stay current** - Update or delete
6. **Check costs** - LLM calls add up
7. **Read the code** - When docs are unclear, code is truth

---

*This workflow ensures consistent, trackable progress. All work flows through GitHub issues and PRs, creating a complete audit trail.*
