<critical_instructions>
## COST AWARENESS - READ THIS FIRST

**This pipeline costs real money via OpenRouter API calls.**

NEVER run these operations without explicit user approval:
- `shelf.py book <scan-id> process` - Full pipeline processing
- `shelf.py book <scan-id> stage <stage> run` - Single stage processing
- `shelf.py batch <stage>` - Library-wide batch stage processing
- Any command that spawns LLM API calls

Safe operations (can run freely):
- `shelf.py library list`, `shelf.py book <scan-id> info`, `pytest tests/`
- `shelf.py book <scan-id> stage <stage> info` - View stage status
- `shelf.py book <scan-id> stage <stage> phase <phase> info` - View phase status
- Reading files, grepping, analyzing code

**Always ask first**
</critical_instructions>

<git_workflow>
## Git Workflow

**Current practice (solo + AI pair programming):**
```
Code → Test → Commit with detailed message → Push to main
```

**Future collaborative workflow:**
```
Issue → Branch → Code → Test → Doc → Commit → PR → Merge
```

**When to branch:**
- Major refactoring (>1000 lines changed)
- Experimental features that might be abandoned
- Breaking changes requiring review
- When you want to compare approaches (PR to self)

**When to commit directly to main:**
- Bug fixes
- Documentation updates
- Small refactorings
- Incremental feature development (solo work)

**Commit message structure:**
```bash
<type>: <imperative summary (50 chars)>

<markdown-formatted body>

**Problem:** What issue was being solved
**Solution:** How it was solved
**Changes:** File-level summary with bullet points
**Impact:** User-facing or architectural effects
**Why these changes:** Decision rationale

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**Commit types:**
- `feat`: New feature
- `fix`: Bug fix
- `refactor`: Code restructuring (no behavior change)
- `docs`: Documentation changes
- `chore`: Maintenance tasks (deps, config)
- `test`: Test additions/changes

**Commit atomicity:**
- One **logical** change per commit (not necessarily one file)
- System-wide refactorings can touch many files in one commit
- Each commit should be independently understandable
- Large commits OK if they represent ONE architectural decision

**Examples:**
- ✅ `refactor: replace CheckpointManager with MetricsManager` (30 files)
- ✅ `fix: correct import path for llm_result_to_metrics` (1 file)
- ❌ `update: multiple unrelated things` (any file count)

**AI collaboration attribution (REQUIRED):**
All commits co-authored with Claude Code must include:
```
🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude <noreply@anthropic.com>
```

**History management:**
- Prefer linear history (rebase over merge)
- Preserve work history (don't squash unless duplicative)
- NEVER force-push to main
</git_workflow>

<pipeline>
## Pipeline Architecture

**Stages (in order):**
1. `ocr-pages` - Vision OCR using OlmOCR (per-page JSON output)
2. `label-structure` - Classify page content blocks (body, footnotes, headers)
3. `extract-toc` - Extract table of contents from identified ToC pages
4. `link-toc` - Link ToC entries to page numbers
5. `common-structure` - Build unified structure from ToC and labels
6. `epub-output` - Generate ePub 3.0 from structure

**CLI hierarchy:**
```bash
# Stage operations
shelf book <scan-id> stage <stage> run [--workers N] [--model M]
shelf book <scan-id> stage <stage> info
shelf book <scan-id> stage <stage> clean -y
shelf book <scan-id> stage <stage> report [--filter "key=value"]

# Phase operations (within a stage)
shelf book <scan-id> stage <stage> phase <phase> info
shelf book <scan-id> stage <stage> phase <phase> clean -y
```

**Stage Registry:**
`infra/pipeline/registry.py` - Single source of truth for all stages

**Reference implementations:**
- Simple: `pipeline/ocr_pages/`
- Multi-phase: `pipeline/extract_toc/`
- Non-LLM: `pipeline/common_structure/`
</pipeline>

<quick_reference>
## Quick Reference

**Architecture Decisions:**
`docs/decisions/` contains ADRs that explain WHY the code is designed this way.

**Start here: `docs/decisions/000-information-hygiene.md`**

Core ADRs:
- **000 (Information Hygiene)** - Context clarity as first principle
- **001 (Think Data First)** - Ground truth from disk
- **002 (Stage Independence)** - Communicate through files
- **003 (Cost Tracking)** - Economics shape architecture
- **006 (File Organization)** - Small files, clear purpose
- **007 (Naming Conventions)** - Hyphens for stage names, underscores for modules

---

**Core principles (from ADRs):**
- **Ground truth from disk** (ADR 001) - Files are reality, not in-memory state
- **If-gates for resume** - Check progress, refresh, continue
- **Incremental metrics** - Record after each page via MetricsManager
- **Stage independence** (ADR 002) - Communicate through files, not imports
- **One schema per file** (ADR 006) - Easy to find, easy to modify

**Naming convention (CRITICAL):**
- Stage names use hyphens: `ocr-pages`, `extract-toc`, `label-structure`
- NEVER use underscores in stage names (causes lookup failures)
- Python modules use underscores: `pipeline/ocr_pages/`, `pipeline/extract_toc/`
- See ADR 007 for full rationale

---

**Environment:**
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
</quick_reference>

<remember>
## Remember - Critical Checklist

**0. ARCHITECTURE DECISIONS**
- Read `docs/decisions/` to understand WHY the code is designed this way
- Core ADRs: 000 (Information Hygiene), 001 (Data First), 002 (Stage Independence), 003 (Cost Tracking)
- When in doubt about a design choice, check the ADRs first

**1. COST AWARENESS (ADR 003)**
- ALWAYS ask before running expensive operations
- Test on samples, not full books
- Check `stage info` before running to see what will be processed

**2. GIT WORKFLOW**
- Direct to main for solo work; branch for major refactors
- Commit format: `<type>: <imperative summary>` + markdown body
- One logical change per commit (may touch many files)
- ALWAYS include AI collaboration attribution

**3. STAGE/PHASE IMPLEMENTATION (ADR 001, 002)**
- Reference implementations: `pipeline/ocr_pages/`, `pipeline/extract_toc/`
- Stage names use HYPHENS: `ocr-pages` not `ocr_pages` (ADR 007)
- Ground truth from disk (ADR 001)
- Stage independence - files, not imports (ADR 002)
- If-gates for resume, incremental metrics
- Phases use `PhaseStatusTracker` / `MultiPhaseStatusTracker`

**4. CODE HYGIENE (ADR 000, 006)**
- Small files, one concept per file (ADR 006)
- Comments explain WHY, not WHAT (prefer obvious code)
- Delete dead code aggressively (git preserves history)
- Simplicity over cleverness

**5. DOCUMENTATION**
- Update with code changes (not after)
- Code is source of truth
- Point to code rather than duplicate it
</remember>
