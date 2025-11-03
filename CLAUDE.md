<critical_instructions>
## COST AWARENESS - READ THIS FIRST

**This pipeline costs real money via OpenRouter API calls.**

NEVER run these operations without explicit user approval:
- `shelf.py book <scan-id> process` - Full pipeline processing
- `shelf.py book <scan-id> run-stage <stage>` - Single stage processing
- `shelf.py batch <stage>` - Library-wide batch stage processing
- Any command that spawns LLM API calls (paragraph-correct, label-pages, extract_toc)

Safe operations (can run freely):
- `shelf.py library list`, `shelf.py book <scan-id> info`, `pytest tests/`
- Reading files, grepping, analyzing code

**Always ask first**
</critical_instructions>

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

<stage_implementation>
## Stage Implementation

**OCR is the reference implementation.**
Read `pipeline/ocr/` and `docs/guides/implementing-a-stage.md` for full details.

**Core principles:**
1. **One schema per file** - Easy to find, easy to modify
2. **Ground truth from disk** - Files are reality, not metrics state
3. **If-gates for resume** - Each phase checks progress, refreshes, continues
4. **Incremental progress** - Metrics recorded after each page via MetricsManager
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
def run(self, storage, logger):
    progress = self.get_status(storage, logger)

    if progress["remaining_pages"]:
        process_pages()
        progress = self.get_status(storage, logger)  # Refresh

    if not progress["artifacts"]["report_exists"]:
        generate_report()

    # Completion determined by status tracker checking disk state
```

**Naming conventions (CRITICAL):**
- Stage names ALWAYS use hyphens: `paragraph-correct`, `label-pages`, `extract-toc`
- NEVER use underscores in stage names (causes lookup failures)
- Use `storage.stage("stage-name")` - exact string, no manipulation
- Why: Consistency between CLI args, directory names, and storage lookups
- Violation causes: "Page not found" errors, empty grep results, wrong log directories
</stage_implementation>

<prompts>
## Prompt Engineering

**Teach concepts that generalize**

**Use XML tags for structure**

**Avoid overfitting (CRITICAL):**
- THIS IS A REALLY IMPORTANT ONE!
- Don't add examples from text we are processing.
- If you feel this urge think generally about the problem and how to solve it as a more general case

**Example of overfitting (WRONG):**
```
Pattern: Parent entries without page numbers
Example: "Part I: April 12, 1945" followed by "The First Days ... 15"
```
This teaches the model to recognize THIS SPECIFIC BOOK, not the pattern.

**Example of proper teaching (RIGHT):**
```
Pattern: Parent entries without page numbers
Visual signs:
- NO page number visible
- Followed by indented entries that DO have page numbers
- Often styled differently (bold, larger, "Part I", "Section A")

Example (generic):
"Part I: The Ancient World" followed by "Chapter 1: Early Civilizations ... 1"
```
This teaches WHAT TO LOOK FOR, not what the current book contains.

**Pattern-based teaching:**
- Show the abstract pattern first (visual signs, structural properties)
- Then provide generic examples that could apply to any book
- Use made-up content: "Ancient World", "Medieval Period", "Industrial Era"
- NEVER use actual chapter titles from the book being processed

**Design patterns:**
1. Vision-first workflow
2. Philosophy over rules (teach WHAT/WHY, then HOW)
3. Handle failure modes explicitly

**Before finalizing:** Would it work on unseen books?
</prompts>


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

<cli_design>
## CLI Design Principles

**Explicit over convenient:**
- Destructive operations should have scary names
- WRONG: `--force` (vague, sounds convenient)
- RIGHT: `--delete-outputs` (explicit about what gets destroyed)

**Confirmation for destruction:**
- Add `-y/--yes` flag to skip confirmation
- Default: require typing "yes" for irreversible operations
- Warning format: `⚠️  WARNING: --delete-outputs will DELETE all existing outputs for N books`

**Help text clarity:**
- Warn about irreversibility: `(WARNING: irreversible)`
- Show operators for filters: `Operators: = > < >= <=`
- Be specific: "DELETE all stage outputs" not "clean stage"

**Single source of truth:**
- Stage registry in ONE place: `cli/constants.py::STAGE_DEFINITIONS`
- Dynamic stage map building via `get_stage_map()`
- Never hardcode stage lists in multiple files
- CLI parsers use `CORE_STAGES`, library commands use `STAGE_ABBRS`
</cli_design>

<code_hygiene>
## Code Hygiene

**Dead code accumulates:**
- Files that exist but are never imported or registered
- Run periodic audits: grep for imports, check CLI parser registration
- Delete aggressively - git preserves history if you need it back

**Comments explain WHY, not WHAT:**
- WRONG: `# Build kwargs for stage initialization`
- RIGHT: `# OCR stages need worker control for CPU-bound parallelism`
- WRONG: `# Single source of truth for stage definitions`
- RIGHT: (no comment - code structure makes this obvious)

**Simplicity over cleverness:**
- If you need comments to explain the code, simplify the code
- Prefer `shutil.rmtree()` over `for file in dir: if not .gitkeep: delete`
- Explicit is better than implicit, but obvious is better than explicit

**Docstrings for non-obvious decisions:**
- Explain WHY stages need different initialization parameters
- Explain WHAT gets preserved/destroyed in destructive operations
- Explain HOW resume logic works (ground truth from disk)
</code_hygiene>

<remember>
## Remember - Critical Checklist

**1. COST AWARENESS**
- ALWAYS ask before running expensive operations
- Test on samples, not full books
- Check costs: `shelf.py book <scan-id> info`

**2. GIT WORKFLOW**
- One source of truth: main branch
- Issue → Branch → Code → Test → Doc → Commit → PR
- Commit format: `<type>: <description>` (feat/fix/docs/refactor/test/chore)

**3. STAGE IMPLEMENTATION**
- **OCR is the reference** - read `pipeline/ocr/` when stuck
- Stage names use HYPHENS: `paragraph-correct` not `paragraph_correct`
- One schema per file
- Ground truth from disk (not metrics state)
- If-gates for resume (check progress, refresh, continue)
- Incremental metrics (record after each page via MetricsManager)

**4. SCHEMAS**
- Three schemas: output, metrics, report
- Always validate: pass schema to `save_page`/`load_page`
- Never skip validation

**5. PROMPTS**
- Teach patterns that generalize, never reference test data
- Use generic examples: "Ancient World", "Medieval Period" (not actual book content)
- Pattern-based teaching: show visual signs + structural properties first
- XML tags: `<role>`, `<critical_instructions>`, `<task>`, `<output_requirements>`
- Primacy/recency: critical info at START and END

**6. CLI DESIGN**
- Destructive operations need scary names: `--delete-outputs` not `--force`
- Require confirmation for irreversible operations (unless `-y`)
- Help text warns about destructiveness
- Single source of truth: `cli/constants.py::STAGE_DEFINITIONS`

**7. CODE HYGIENE**
- Comments explain WHY, not WHAT
- Delete dead code aggressively (git preserves history)
- Simplicity over cleverness
- Run periodic audits for unused files/imports

**8. DOCUMENTATION**
- Update with code changes (not after)
- No "v2" docs - update in place
- Code is source of truth
</remember>