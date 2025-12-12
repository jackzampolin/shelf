# Shelf - Turn Physical Books into Digital Libraries

A vision-powered pipeline that transforms scanned books into structured digital text using local OCR and multimodal LLMs.

---

## Quick Start

```bash
# Setup
git clone https://github.com/jackzampolin/shelf
cd shelf

uv venv
source .venv/bin/activate
uv pip install -e .

# Initialize config
uv run python shelf.py config init
# Add your API keys when prompted

# Verify
uv run python shelf.py --help
```

---

## Usage

### Library Management

```bash
# Add books to the library
uv run python shelf.py library add ~/Documents/Scans/book-*.pdf
uv run python shelf.py library add ~/Documents/Scans/book.pdf --run-ocr

# View all books
uv run python shelf.py library list
uv run python shelf.py library list --json

# View library statistics
uv run python shelf.py library stats

# Delete a book
uv run python shelf.py library delete <scan-id>
uv run python shelf.py library delete <scan-id> --yes  # Skip confirmation
```

### Single Book Processing

Process individual books through pipeline stages:

```bash
# View book status and pipeline progress
uv run python shelf.py book <scan-id> info
uv run python shelf.py book <scan-id> info --json

# Run full pipeline
uv run python shelf.py book <scan-id> process
uv run python shelf.py book <scan-id> process --delete-outputs  # Delete all outputs first
```

### Stage Operations

```bash
# View stage status (shows phases)
uv run python shelf.py book <scan-id> stage ocr-pages info
uv run python shelf.py book <scan-id> stage extract-toc status  # 'status' is alias for 'info'

# Run a single stage
uv run python shelf.py book <scan-id> stage ocr-pages run --workers 30
uv run python shelf.py book <scan-id> stage extract-toc run --model gpt-4o

# Clean stage outputs
uv run python shelf.py book <scan-id> stage ocr-pages clean -y
```

### Phase Operations

Phases are sub-units within stages. Clean individual phases to re-run specific parts:

```bash
# View phase status
uv run python shelf.py book <scan-id> stage ocr-pages phase blend info

# Clean a single phase (then re-run the stage to resume from that phase)
uv run python shelf.py book <scan-id> stage ocr-pages phase blend clean -y
uv run python shelf.py book <scan-id> stage ocr-pages run  # Resumes at blend phase
```

**Pipeline Stages:**
1. **ocr-pages** - Vision OCR using OlmOCR (API-based)
2. **label-structure** - Classify content blocks (body, footnotes, headers)
3. **extract-toc** - Extract table of contents entries
4. **link-toc** - Link ToC entries to page numbers
5. **common-structure** - Build unified book structure
6. **epub-output** - Generate ePub 3.0 file

**Pipeline Flow:**
```
PDF → Split → OCR → Label → Extract ToC → Link ToC → Structure → ePub
```

**Note:** All stages auto-resume from progress if interrupted. Metrics tracked for cost and time.


### Library-wide Batch Processing

Run stages across all books in your library:

```bash
# Run a stage across all books (persistent random order)
uv run python shelf.py batch ocr-pages
uv run python shelf.py batch label-structure --model gpt-4o

# Control processing order
uv run python shelf.py batch ocr-pages --reshuffle  # Create new random order
uv run python shelf.py batch ocr-pages --force      # Regenerate completed books

# Customize workers for parallel processing
uv run python shelf.py batch ocr-pages --workers 10
```

**Batch features:**
- **Persistent shuffle** - Order saved to `.library.json`, reused across restarts
- **Smart resume** - Skips already-completed books
- **Auto-sync** - Adding/deleting books automatically updates shuffle orders

### Web Interface

Debug and visually review pipeline outputs:

```bash
# Start web viewer
uv run python shelf.py serve

# Or with custom port
uv run python shelf.py serve --port 8080
```

---

## Current Status

✅ **Pipeline Stages (ADR-compliant):**
- **ocr-pages** - Vision OCR via OlmOCR
- **label-structure** - Block classification (body, footnotes, headers)
- **extract-toc** - Multi-phase ToC extraction
- **link-toc** - ToC to page linking
- **common-structure** - Unified structure building
- **epub-output** - ePub 3.0 generation

**Current Focus:** Testing pipeline on diverse books and improving extraction quality

---

## Testing

```bash
# Run all tests
uv run python -m pytest tests/ -v

# Run specific modules
uv run python -m pytest tests/infra/ -v
uv run python -m pytest tests/tools/ -v
```

---

## Documentation

### For Contributors
- [CLAUDE.md](CLAUDE.md) - AI workflow guide and codebase conventions

### Architectural Decision Records (ADRs)
- [ADR 000: Information Hygiene](docs/decisions/000-information-hygiene.md) - Context clarity as first principle
- [ADR 001: Think Data First](docs/decisions/001-think-data-first.md) - Ground truth from disk
- [ADR 002: Stage Independence](docs/decisions/002-stage-independence.md) - Unix philosophy applied
- [ADR 003: Cost Tracking](docs/decisions/003-cost-tracking-first-class.md) - Economics shape architecture
- [ADR 004: OpenRouter API](docs/decisions/004-openrouter-api.md) - LLM provider choice
- [ADR 005: Clean Working Tree](docs/decisions/005-clean-working-tree.md) - Git discipline
- [ADR 006: File Organization](docs/decisions/006-file-organization.md) - Small files, clear purpose
- [ADR 007: Naming Conventions](docs/decisions/007-naming-conventions.md) - Consistency prevents bugs

### Reference Implementations
- **Simple stage:** `pipeline/ocr_pages/`
- **Multi-phase stage:** `pipeline/extract_toc/`
- **Non-LLM stage:** `pipeline/common_structure/`

---

## Architecture

### High-Level Design

Shelf uses a **Stage abstraction pattern** for composable, resumable, testable pipeline processing:

**Core Components:**
1. **BaseStage** - Three-hook lifecycle (before/run/after) with schema-driven validation
2. **Storage System** - Three-tier hierarchy (Library → Book → Stage)
3. **MetricsManager** - Atomic progress tracking and cost/time metrics
4. **PipelineLogger** - Dual-output logging (JSON + human-readable)

**Key Properties:**
- **Resumable** - Ground truth from disk, resume from exact point of interruption
- **Type-safe** - Pydantic schemas validate data at boundaries
- **Cost-aware** - Track every API call financially via MetricsManager
- **Independent** - Stages evolve separately, communicate via files (ADR 002)
- **Testable** - Test stages in isolation with mock data

See ADRs in `docs/decisions/` for detailed design philosophy.

### Pipeline Flow

```
PDF → Split → OCR → Label → Extract ToC → Link ToC → Structure → ePub
```

**Stages:**
1. **ocr-pages** - Vision OCR using OlmOCR → `ocr-pages/page_NNNN.json`
2. **label-structure** - Classify blocks (body, footnotes, headers) → `label-structure/page_NNNN.json`
3. **extract-toc** - Multi-phase ToC extraction → `extract-toc/toc.json`
4. **link-toc** - Link ToC entries to pages → `link-toc/linked_toc.json`
5. **common-structure** - Build unified structure → `common-structure/structure.json`
6. **epub-output** - Generate ePub 3.0 → `{scan-id}.epub`

Each stage:
- Validates inputs in `before()` hook
- Processes pages in `run()` hook (controls own parallelization)
- Tracks costs, timing, and metrics via MetricsManager
- Resumes automatically from progress if interrupted (ADR 001)

### Storage Structure

```
~/Documents/shelf/
├── .library.json             # Library-wide operational state
├── {scan-id}/                # Per-book directory (BookStorage)
│   ├── metadata.json         # Book metadata (title, author, year)
│   ├── {scan-id}.epub        # Generated ePub output
│   ├── source/               # Original page images
│   ├── ocr-pages/            # Vision OCR outputs
│   │   ├── page_NNNN.json    # Per-page OCR results
│   │   ├── metrics.json      # Progress, cost, timing
│   │   └── logs/
│   ├── label-structure/      # Block classification outputs
│   │   ├── page_NNNN.json
│   │   ├── metrics.json
│   │   └── logs/
│   ├── extract-toc/          # ToC extraction outputs
│   │   ├── toc.json          # Final ToC
│   │   ├── metrics.json
│   │   └── logs/
│   ├── link-toc/             # ToC linking outputs
│   │   ├── linked_toc.json
│   │   └── metrics.json
│   ├── common-structure/     # Unified structure
│   │   └── structure.json
│   └── epub-output/          # ePub generation metadata
│       └── metadata.json
```

**Key points:**
- Filesystem is source of truth (ADR 001)
- Each stage has independent metrics and logs
- Schemas enforce type safety at boundaries
- MetricsManager provides atomic progress tracking
- Resume from disk state, not in-memory state

