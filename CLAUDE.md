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

**Teach concepts that generalize**

**Use XML tags for structure**

**Avoid overfitting (CRITICAL):**
- THIS IS A REALLY IMPORTANT ONE!
- Don't add examples from text we are processing
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

<quick_reference>
## Quick Reference

**Stage Implementation:**
See `docs/guides/implementing-a-stage.md` for complete guide.

Reference implementations:
- Simple: `pipeline/ocr_pages/`
- Complex: `pipeline/label_pages/`
- Non-LLM: `pipeline/find_toc/`

Core principles:
- **Ground truth from disk** - Files are reality, not in-memory state
- **If-gates for resume** - Check progress, refresh, continue
- **Incremental metrics** - Record after each page via MetricsManager
- **Stage independence** - Communicate through files, not imports
- **One schema per file** - Easy to find, easy to modify

**Naming convention (CRITICAL):**
- Stage names use hyphens: `ocr-pages`, `find-toc`, `extract-toc`
- NEVER use underscores in stage names (causes lookup failures)

**Stage Registry:**
`infra/pipeline/registry.py` - Single source of truth for all stages

**Architecture Decisions:**
See `docs/decisions/` for detailed rationale:
- `000-information-hygiene.md` - Context clarity as first principle
- `001-think-data-first.md` - Ground truth from disk
- `002-stage-independence.md` - Files over imports
- `007-naming-conventions.md` - Hyphens in stage names

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

**1. COST AWARENESS**
- ALWAYS ask before running expensive operations
- Test on samples, not full books

**2. GIT WORKFLOW**
- Direct to main for solo work; branch for major refactors
- Commit format: `<type>: <imperative summary>` + markdown body
- One logical change per commit (may touch many files)
- ALWAYS include AI collaboration attribution

**3. STAGE IMPLEMENTATION**
- Read `docs/guides/implementing-a-stage.md` first
- Reference implementations: `pipeline/ocr_pages/`, `pipeline/label_pages/`
- Stage names use HYPHENS: `ocr-pages` not `ocr_pages`
- Ground truth from disk (not in-memory state)
- If-gates for resume (check progress, refresh, continue)
- Incremental metrics (record after each page)

**4. PROMPTS**
- Teach patterns that generalize, never reference test data
- Use generic examples: "Ancient World", "Medieval Period" (not actual book content)
- Pattern-based teaching: visual signs + structural properties first

**5. CODE HYGIENE**
- Comments explain WHY, not WHAT (prefer obvious code over comments)
- Delete dead code aggressively (git preserves history)
- Simplicity over cleverness

**6. DOCUMENTATION**
- Update with code changes (not after)
- Code is source of truth
- Point to code rather than duplicate it
</remember>
