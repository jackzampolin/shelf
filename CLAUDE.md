# AI Assistant Workflow Guide

## First Things First

When starting any session:
1. Run `tree -L 2 --gitignore` to see current repo structure
2. Check `git status` for current state
3. Review open issues on GitHub
4. Check the project board for priorities

## Core Workflow Principles

### Git as Source of Truth
- **Current state**: Lives on main branch only
- **History**: Lives in git commits
- **Planning**: Lives in GitHub issues/projects
- **Never**: Keep old versions, drafts, or outdated docs

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

## Git Operations

### Branching
```bash
# Always from main
git checkout main
git pull
git checkout -b <type>/<description>

# Types:
# - feature/ (new functionality)
# - fix/ (bug fixes)
# - docs/ (documentation only)
# - refactor/ (code improvements)
```

### Committing
```bash
# Atomic commits after logical sections
git add <files>
git commit -m "<type>: <present-tense-description>"

# Types: feat, fix, docs, refactor, test, chore
```

Examples:
- `feat: add quote extraction for biographies`
- `fix: handle empty source documents`
- `docs: update setup instructions`

### Pull Requests
When creating PRs:
1. Link to the issue: "Fixes #123"
2. Describe what changed and why
3. Confirm tests pass
4. Confirm docs updated

## GitHub Organization

### Issue Creation
Every issue should have:
- Clear title
- Labels (at minimum one of: `development`, `documentation`, `bug`, `enhancement`)
- For research items add: `person:<name>` or `topic:<topic>`
- Assignment to project board
- Milestone if applicable

### Issue Labels
Core labels:
- `development` - Code work
- `documentation` - Docs updates
- `bug` - Something broken
- `enhancement` - Improvements
- `research` - Research tasks

Entity labels:
- `person:<lastname>` - For biographical work
- `topic:<keyword>` - For thematic research

## Testing Discipline

Before any commit:
```bash
# Run tests if they exist
pytest tests/  # or appropriate test command

# Check for syntax errors
python -m py_compile src/**/*.py

# Verify documentation is current
# (Manually check if automated check doesn't exist)
```

## Documentation Updates

When code changes:
1. Update relevant docs immediately
2. Never create "v2" docs - update in place
3. Remove outdated sections
4. Keep examples current

## Working with Existing Files

Before modifying:
1. Understand current patterns
2. Follow existing conventions
3. Don't introduce new patterns without discussion
4. Check git history if unclear: `git log -p <file>`

## Environment Setup

### Python Virtual Environment

This project uses `uv` for Python package management:

```bash
# First-time setup
uv venv                               # Create virtual environment
source .venv/bin/activate             # Activate it
uv pip install -r pyproject.toml      # Install dependencies

# Running scripts
python scan_intake.py                 # Always use python, not python3
```

The `pyproject.toml` file tracks all dependencies. When adding new packages:
```bash
# Add to pyproject.toml dependencies array, then:
uv pip install -r pyproject.toml
```

### Secrets Management

Never commit secrets:
```bash
# Check .env.example for required variables
cp .env.example .env
# Edit .env with actual values
# Ensure .env is in .gitignore
```

## Automation Triggers

GitHub Actions will run on:
- Push to any branch (tests)
- PR creation/update (full checks)
- Merge to main (deployment/updates)

## Quick Decision Guide

**Starting work?**
- Check issues first
- Create branch from main
- Run tree to see structure

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

## Scanshelf Specific Patterns

### Project Architecture

This is a **book processing pipeline** for historical research:

```
Scan (PDF) → OCR → LLM Correction → Structure → Query API
```

**Key Concepts:**
- **Library**: `~/Documents/book_scans/library.json` - catalog of all books
- **Scan ID**: Random Docker-style name (e.g., "modest-lovelace")
- **Pipeline Stages**: OCR → Correct → Fix → Structure
- **Data Products**: Pages (provenance) → Chapters (reading) → Chunks (RAG)

### Using the CLI (`ar.py`)

The unified CLI is the main interface. **CRITICAL: `ar` is shorthand - you MUST actually run `uv run python ar.py <command>`**

Example:
```bash
# WRONG (will fail with "ar: illegal option"):
ar library list

# CORRECT:
uv run python ar.py library list
```

For brevity in these docs, we show `ar <command>`, but **always expand it to `uv run python ar.py <command>` in actual commands**.

**Library Management:**
```bash
ar library list                    # See what books exist (run as: uv run python ar.py library list)
ar library show <scan-id>          # Get book details
ar library stats                   # Collection statistics
ar library add <directory>      # Smart add with LLM metadata
```

**Processing Pipeline:**
```bash
ar process <scan-id>               # Run full pipeline (all stages)
ar ocr <scan-id>                   # Stage 1: OCR only
ar correct <scan-id>               # Stage 2: LLM corrections only
ar fix <scan-id>                   # Stage 3: Agent 4 targeted fixes
ar structure <scan-id>             # Stage 4: Chapter/chunk structure
```

**Monitoring:**
```bash
ar status <scan-id>                # Quick status check
ar monitor <scan-id>               # Real-time progress with ETA
```

**Common Patterns:**
```bash
# Discover available books to add
ar library discover ~/Documents/Scans

# Compare available vs. added books
ar library list                    # See what's already in library
ar library discover ~/Documents/Scans  # See what PDFs are available
# Compare the two lists to find books not yet added

# Add a new book (run added on specific directory)
ar library add ~/Documents/Scans/fiery-peace-1.pdf ~/Documents/Scans/fiery-peace-2.pdf ...

# Process it completely
ar process modest-lovelace

# Check progress
ar status modest-lovelace --watch

# View results
ar library show modest-lovelace
```

### Data Structure Understanding

**Storage Layout:**
```
~/Documents/book_scans/
├── library.json              # Catalog (single source of truth)
└── <scan-id>/                # One per scan
    ├── source/               # Original PDF
    ├── ocr/                  # Raw OCR (page_*.json)
    ├── corrected/            # LLM corrected (page_*.json)
    ├── structured/           # Semantic structure
    │   ├── chapters/         # Chapter JSON + markdown
    │   ├── chunks/           # ~5-page RAG chunks
    │   ├── full_book.md      # Complete markdown
    │   └── metadata.json     # Structure metadata
    └── logs/                 # Processing logs
```

**Important Files:**
- `library.json`: Maps scan IDs to books, tracks metadata
- `structured/metadata.json`: Chapter breakdown, chunk count, costs
- `structured/chunks/chunk_*.json`: Semantic chunks with provenance
- `metadata.json` (in scan root): Per-scan processing history

**Data Flow:**
1. PDF → OCR → `ocr/page_*.json` (raw text)
2. OCR → Correction → `corrected/page_*.json` (cleaned text)
3. Corrected → Agent 4 → `corrected/page_*.json` (overwrites in place)
4. Corrected → Structure → `structured/` (chapters + chunks)

### Working with Books

**When asked to query books:**
1. First run: `ar library list` to see available books
2. Get scan_id for the book you want
3. Check if structured: `ar library show <scan-id>`
4. If using MCP: Use MCP tools (list_books, search_book, etc.)
5. If direct access: Read from `~/Documents/book_scans/<scan-id>/structured/`

**Example:**
```bash
# User asks: "Find mentions of Truman in The Accidental President"

# Step 1: Find the scan ID
ar library list
# Output shows: modest-lovelace is The Accidental President

# Step 2: Search (if using structured data directly)
grep -i "truman" ~/Documents/book_scans/modest-lovelace/structured/chunks/*.json

# Or use MCP if configured:
# MCP tool: search_book(scan_id="modest-lovelace", query="truman")
```

### MCP Server Integration

The MCP server (`mcp_server.py`) provides Claude Desktop direct access to books.

**Available Tools:**
- `list_books`: See all books in library
- `get_book_info(scan_id)`: Book details + chapters
- `search_book(scan_id, query)`: Full-text search
- `get_chapter(scan_id, chapter_number)`: Full chapter text
- `get_chunk(scan_id, chunk_id)`: Specific chunk
- `get_chunk_context(scan_id, chunk_id, before, after)`: Chunk with context
- `list_chapters(scan_id)`: Chapter metadata
- `list_chunks(scan_id, chapter)`: Chunk summaries

**Setup:** See `docs/MCP_SETUP.md`

### Cost Awareness

This pipeline costs money (OpenRouter API). Be mindful:

**Per-Book Costs (447-page example):**
- OCR: Free (Tesseract)
- Correct: ~$10 (gpt-4o-mini, 30 workers)
- Fix: ~$1 (Claude, targeted fixes only)
- Structure: ~$0.50 (Claude Sonnet 4.5, one pass)
- **Total: ~$12/book**

**When suggesting changes:**
- Don't re-run stages unnecessarily
- Use `--start` and `--end` flags to limit page ranges for testing
- Test prompts on small samples first
- Consider model choice (gpt-4o-mini vs Claude)

### Adding New Features

**Before adding code:**
1. Check if it belongs in: `pipeline/`, `tools/`, or root
2. `pipeline/`: Sequential processing stages (OCR → Correct → Fix → Structure)
3. `tools/`: Supporting utilities (library, monitor, review, scan)
4. Root: Infrastructure (CLI, config, MCP server)

**Common Changes:**
- New pipeline stage → Add to `pipeline/`, update `pipeline/run.py`
- New CLI command → Add to `ar.py` subcommands
- New query capability → Add to `mcp_server.py` tools
- New library feature → Update `tools/library.py`

### File Naming Conventions

- Pages: `page_001.json`, `page_002.json` (zero-padded, 3 digits)
- Chunks: `chunk_001.json`, `chunk_002.json` (zero-padded, 3 digits)
- Chapters: `chapter_01.json`, `chapter_01.md` (zero-padded, 2 digits)
- Scan IDs: `<adjective>-<scientist>` (e.g., "modest-lovelace", "wonderful-dirac")

### Dependencies Management

When adding dependencies:
```bash
# 1. Add to pyproject.toml
# 2. Install
uv pip install -e .
# 3. Test import
python -c "import <package>"
```

**Current key dependencies:**
- `pytesseract`: OCR
- `requests`: API calls (OpenRouter)
- `python-dotenv`: Config management
- `mcp`: MCP server protocol
- `pdf2image`: PDF processing
- `pillow`, `opencv-python`: Image handling

## Remember

1. **One source of truth** - Main branch is reality
2. **Issues before code** - Plan in GitHub
3. **Test everything** - No untested code
4. **Commit often** - Logical, atomic chunks
5. **Docs stay current** - Update or delete
6. **Use `ar` CLI** - Don't run scripts directly
7. **Check costs** - LLM calls add up
8. **Scan IDs not slugs** - Use random IDs for scans

---

*This workflow ensures consistent, trackable progress. All work flows through GitHub issues and PRs, creating a complete audit trail.*