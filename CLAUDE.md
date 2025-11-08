<critical_instructions>
## COST AWARENESS - READ THIS FIRST

**This pipeline costs real money via OpenRouter API calls.**

NEVER run these operations without explicit user approval:
- `shelf.py book <scan-id> process` - Full pipeline processing
- `shelf.py book <scan-id> run-stage <stage>` - Single stage processing
- `shelf.py batch <stage>` - Library-wide batch stage processing
- Any command that spawns LLM API calls (ocr-pages, find-toc, extract-toc, label-pages, link-toc)

Safe operations (can run freely):
- `shelf.py library list`, `shelf.py book <scan-id> info`, `pytest tests/`
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

<prompts>
## Prompt Engineering

**See `docs/prompts/handbook.md` for complete guide.**

**5 Core Principles:**
1. **Information Hygiene** - Structure for clarity (XML tags, clear scope)
2. **Teach Generalization** - Principles transfer, examples don't
3. **Triangulate Truth** - Cross-verify sources (grep + vision + OCR)
4. **Anticipate Failure** - Name pitfalls explicitly, calibrate confidence
5. **Economics-Aware** - Cost shapes strategy (FREE → CHEAP → EXPENSIVE)

**CRITICAL - Avoid overfitting:**
- NEVER use actual book content in examples
- Use generic placeholders: "Ancient World", "Medieval Period"
- Test: Would this example work for ANY book?

**Example of overfitting (WRONG):**
```
Example: "Part I: April 12, 1945" followed by "The First Days ... 15"
```
→ Teaches model to recognize THIS BOOK, not the pattern.

**Example of proper teaching (RIGHT):**
```
Pattern: Parent entries without page numbers
Visual signs: No page # + indented children below with page #s
Example: "Part I: Ancient World" → "Chapter 1: Early Civilizations ... 1"
```
→ Teaches WHAT TO LOOK FOR, generalizes to all books.

**Detailed techniques:** `docs/prompts/techniques/`
- `generic-examples.md` - Avoid overfitting
- `pattern-based-teaching.md` - Teach visual signs
- `xml-structure.md` - Structure long prompts
- `cost-awareness.md` - Optimize expensive operations
- [8 more technique files]

**Before finalizing:** Would it work on unseen books?
</prompts>

<quick_reference>
## Quick Reference

**Architecture Decisions:**

**Start here: `docs/decisions/000-information-hygiene.md`**

This is THE foundational principle. Everything else flows from it:
- Designed for AI-human pair programming
- Optimize all organization for rapid context acquisition
- Explains the "why" behind the code you see

The rest of `docs/decisions/` (001-007) implement this principle. Read 000 first, others as needed.

---

**Stage Implementation:**
See `docs/guides/implementing-a-stage.md` for complete guide.

Reference implementations:
- Simple: `pipeline/ocr_pages/`
- Complex: `pipeline/label_pages/`
- Non-LLM: `pipeline/find_toc/`

Core principles (from ADRs):
- **Ground truth from disk** (ADR 001) - Files are reality, not in-memory state
- **If-gates for resume** - Check progress, refresh, continue
- **Incremental metrics** - Record after each page via MetricsManager
- **Stage independence** (ADR 002) - Communicate through files, not imports
- **One schema per file** (ADR 006) - Easy to find, easy to modify

**Naming convention (CRITICAL):**
- Stage names use hyphens: `ocr-pages`, `find-toc`, `extract-toc`
- NEVER use underscores in stage names (causes lookup failures)
- See ADR 007 for full rationale

**Stage Registry:**
`infra/pipeline/registry.py` - Single source of truth for all stages

---

**Prompt Engineering:**
See `docs/prompts/handbook.md` for 5 core principles + techniques

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
- See `cost-awareness.md` technique for prompts

**2. GIT WORKFLOW**
- Direct to main for solo work; branch for major refactors
- Commit format: `<type>: <imperative summary>` + markdown body
- One logical change per commit (may touch many files)
- ALWAYS include AI collaboration attribution

**3. STAGE IMPLEMENTATION (ADR 001, 002)**
- Read `docs/guides/implementing-a-stage.md` first
- Reference implementations: `pipeline/ocr_pages/`, `pipeline/label_pages/`
- Stage names use HYPHENS: `ocr-pages` not `ocr_pages` (ADR 007)
- Ground truth from disk (ADR 001)
- Stage independence - files, not imports (ADR 002)
- If-gates for resume, incremental metrics

**4. PROMPTS**
- See `docs/prompts/handbook.md` for 5 core principles
- CRITICAL: Never use actual book content in examples (avoid overfitting)
- Use generic examples: "Ancient World", "Medieval Period"
- Teach patterns (visual signs) not formats (enumeration)

**5. CODE HYGIENE (ADR 000, 006)**
- Small files, one concept per file (ADR 006)
- Comments explain WHY, not WHAT (prefer obvious code)
- Delete dead code aggressively (git preserves history)
- Simplicity over cleverness

**6. DOCUMENTATION**
- Update with code changes (not after)
- Code is source of truth
- Point to code rather than duplicate it
</remember>
