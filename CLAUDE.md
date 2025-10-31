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

<prompts>
## Prompt Engineering

**Teach concepts that generalize**

**Use XML tags for structure**

**Avoid overfitting:**
- THIS IS A REALLY IMPORTANT ONE! 
- Don't add examples from text we are processing.
- If you feel this urge think generally about the problem and how to solve it as a more general case

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
- Metrics tracked for cost and time records

**4. SCHEMAS**
- Three schemas: output, checkpoint, report
- Always validate: pass schema to `save_page`/`load_page`
- Never skip validation

**5. PROMPTS**
- Teach concepts that generalize, never reference test data
- XML tags: `<role>`, `<critical_instructions>`, `<task>`, `<output_requirements>`
- Primacy/recency: critical info at START and END
- Vision-first workflow

**6. DOCUMENTATION**
- Update with code changes (not after)
- No "v2" docs - update in place
- Code is source of truth
</remember>