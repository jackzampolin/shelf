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
Book processing pipeline:
```
PDF → Split Pages → OCR (Stage 1) → Metadata Extraction →
Correction (Stage 2) → Label (Stage 3) → Merge (Stage 4) →
Structure (Stage 5, in development)
```

**Metadata Extraction** (after OCR, before Correction):
- Analyzes first 10-20 pages of OCR output
- Extracts: title, author, year, publisher, ISBN, book type
- Uses LLM with structured output
- Metadata used by Correction and Label stages
- Tool: `tools/extract_metadata.py` (needs CLI integration)

Each stage produces reports for quality analysis:
- **Correction Report:** `pipeline/2_correction/report.py` - Statistical analysis of OCR corrections
- **Label Report:** `pipeline/3_label/report.py` - Page number extraction and block classification analysis

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
- Test prompts on small samples first
- Use checkpoints to resume interrupted runs
- Check `ar status <scan-id>` for cost tracking

### Current State
- ✅ Infrastructure (`infra/`) - Complete and tested
- ✅ Stage 1: OCR - Complete
- 🚧 Metadata Extraction - Tool exists, needs CLI integration
- ✅ Stage 2: Correction - Complete with vision-based error fixing
- ✅ Stage 3: Label - Complete with page number extraction and block classification
- 🚧 Stage 4: Merge - Implemented, needs testing
- ❌ Stage 5: Structure - In development

**Next Steps:**
1. Integrate metadata extraction into CLI (`ar process metadata`)
2. Run correction and label reports on all 10 books in library
3. Use report data to inform structure stage design
4. Test merge stage on production books
5. Design and implement structure stage based on label analysis

**For current implementation details, see:**
- `README.md` - Usage and commands
- `pipeline/` - Stage implementations
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
