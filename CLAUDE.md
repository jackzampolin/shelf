# AI Assistant Workflow Guide

## ⚠️ REFACTOR IN PROGRESS

**Branch:** `refactor/pipeline-redesign`
**Meta Issue:** [#56 - Pipeline Refactor](https://github.com/jackzampolin/scanshelf/issues/56)
**Architecture & Principles:** See Issue #56 for full context
**Production Patterns:** `docs/standards/` (checkpointing, logging, LLM integration, etc.)

### Multi-Session Refactor Workflow

**Starting a refactor session:**
1. Check [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56) for:
   - Architecture principles (leverage labels, page mapping, etc.)
   - Current progress (which issues complete/pending)
   - Stage flow and cost expectations
2. Pick the next unchecked issue (#57-61)
3. Read the issue for specific implementation guidance
4. Review relevant patterns from `docs/standards/` (see [README](docs/standards/README.md))

**During implementation:**
- Build schemas **iteratively** from observed data (no upfront design)
- Test on actual book data (`accidental-president`) at each stage
- Reference `docs/standards/` for mandatory patterns
- Follow [Production Checklist](docs/standards/09_production_checklist.md)

**Completing a refactor task:**
1. Validate on test book end-to-end
2. Update checklist in Issue #56
3. Commit with reference to issue number
4. Move to next issue

**Key Refactor Principles:**
- **Test-book-driven:** Run on real data, observe, then formalize
- **No speculative design:** Schemas emerge from implementation, not docs
- **Preserve patterns:** Use existing checkpoint, logging, cost tracking patterns
- **Incremental:** Each issue is independently testable

---

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
- `docs/standards/` - Production patterns and standards (refactor source of truth)
- `NEXT_SESSION.md` - Session-specific notes (temporary)

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
uv run python ar.py <command>
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

## Project-Specific Notes

### Architecture
Book processing pipeline: `PDF → OCR → LLM Correction → Merge & Enrich → Structure Detection → Chunk Assembly`

**Current architecture (stages 3-5):** See [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56) for principles and stage flow

### Key Concepts
- **Library:** `~/Documents/book_scans/library.json` - catalog of all books
- **Scan ID:** Random Docker-style name (e.g., "modest-lovelace")
- **Checkpointing:** All stages support resume from interruption
- **Cost tracking:** All LLM calls tracked and logged

### CLI Usage
All commands use `uv run python ar.py <command>`. See `README.md` for current command reference.

### Cost Awareness
This pipeline costs money (OpenRouter API). Be mindful:
- Don't re-run stages unnecessarily
- Use `--start` and `--end` flags to limit page ranges for testing
- Test prompts on small samples first
- Check `docs/standards/` for current cost estimates

### Current State
- ✅ Infrastructure (`infra/`) - Complete and tested
- ✅ Stages 0-2 (Ingest, OCR, Correction) - Complete
- 🚧 Stages 3-5 (Merge, Structure, Chunks) - Implementation in progress

**For current implementation details, see:**
- [Issue #56](https://github.com/jackzampolin/scanshelf/issues/56) - Architecture & principles
- Issues #57-61 - Individual stage implementations
- `README.md` - Usage and commands
- `docs/standards/` - Production patterns
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
