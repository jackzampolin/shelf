# Scanshelf - Turn Physical Books into Digital Libraries

A vision-powered pipeline that transforms scanned books into structured digital text using local OCR and multimodal LLMs.

---

## Quick Start

```bash
# Setup
git clone https://github.com/jackzampolin/scanshelf
cd scanshelf

uv venv
source .venv/bin/activate
uv pip install -e .

# Configure
cp .env.example .env
# Add your OPENROUTER_API_KEY

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
uv run python shelf.py book <scan-id> info --stage ocr-pages
uv run python shelf.py book <scan-id> info --json

# Run full pipeline
uv run python shelf.py book <scan-id> process
uv run python shelf.py book <scan-id> process --clean  # Clean all stages first

# Run single stage
uv run python shelf.py book <scan-id> run-stage tesseract
uv run python shelf.py book <scan-id> run-stage ocr-pages --workers 30
uv run python shelf.py book <scan-id> run-stage find-toc --model gpt-4o
uv run python shelf.py book <scan-id> run-stage extract-toc
```

**Modern Pipeline:**
1. **tesseract** - Fast, free OCR with paragraph-level output (PSM 3, local processing)
2. **ocr-pages** - High-quality vision OCR using OlmOCR (paid API, better accuracy)
3. **find-toc** - Locate table of contents pages using vision analysis
4. **extract-toc** - Extract structured ToC entries from identified pages

**Pipeline Flow:**
```
PDF → Split Pages → [tesseract OR ocr-pages] → find-toc → extract-toc
```

**Choose your OCR:**
- **tesseract**: Free, fast (~1min for 500 pages), good for basic scans
- **ocr-pages**: Paid (~$0.20/book), slow (~10min for 500 pages), excellent accuracy

**Note:** All stages auto-resume from progress if interrupted. Metrics tracked for cost and time.

### Stage Cleanup

```bash
# Clean a stage to restart from scratch
uv run python shelf.py book <scan-id> clean --stage ocr-pages
uv run python shelf.py book <scan-id> clean --stage tesseract --yes  # Skip confirmation
```

### Library-wide Batch Processing

Run stages across all books in your library:

```bash
# Run a stage across all books (persistent random order)
uv run python shelf.py batch ocr-pages
uv run python shelf.py batch find-toc --model x-ai/grok-vision-beta

# Control processing order
uv run python shelf.py batch ocr-pages --reshuffle  # Create new random order
uv run python shelf.py batch ocr-pages --force      # Regenerate completed books

# Customize workers for parallel processing
uv run python shelf.py batch tesseract --workers 10
```

**Batch features:**
- **Persistent shuffle** - Order saved to `.library.json`, reused across restarts
- **Smart resume** - Skips already-completed books
- **Auto-sync** - Adding/deleting books automatically updates shuffle orders

### Debugging & Review

Debug and visually review pipeline outputs with the Shelf Viewer web interface:

```bash
# Start web viewer (Flask + HTMX)
python tools/shelf_viewer.py

# Then open http://127.0.0.1:5001 in your browser
```

**Available viewers:**
- **📖 ToC Viewer** - Review table of contents extraction with page images
- **📊 Stats Viewer** - Aggregate statistics and confidence metrics

**Features:**
- Side-by-side image and data comparison
- HTMX-powered smooth navigation (no full page reloads)
- Responsive design with proper template inheritance

---

## Current Status

✅ **Modern Pipeline (ADR-compliant):**
- **tesseract** - Simple, fast, free local OCR
- **ocr-pages** - High-quality vision OCR via OlmOCR
- **find-toc** - Vision-based ToC page detection
- **extract-toc** - Phase-based ToC extraction

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

### For Users
- [CLAUDE.md](CLAUDE.md) - AI workflow guide for contributors
- [docs/MCP_SETUP.md](docs/MCP_SETUP.md) - Claude Desktop integration

### Architecture Documentation
- [Stage Abstraction](docs/architecture/stage-abstraction.md) - Core pipeline design pattern
- [Storage System](docs/architecture/storage-system.md) - Three-tier storage architecture
- [Checkpoint & Resume](docs/architecture/checkpoint-resume.md) - Resumable processing design
- [Logging & Metrics](docs/architecture/logging-metrics.md) - Observability system

### Developer Guides
- [Implementing a Stage](docs/guides/implementing-a-stage.md) - Step-by-step guide for new stages
- [Troubleshooting](docs/guides/troubleshooting.md) - Common issues and recovery

### Architectural Decision Records (ADRs)
- [ADR 000: Information Hygiene](docs/decisions/000-information-hygiene.md) - Context clarity as first principle
- [ADR 001: Think Data First](docs/decisions/001-think-data-first.md) - Ground truth from disk
- [ADR 002: Stage Independence](docs/decisions/002-stage-independence.md) - Unix philosophy applied
- [ADR 003: Cost Tracking](docs/decisions/003-cost-tracking-first-class.md) - Economics shape architecture
- [ADR 006: File Organization](docs/decisions/006-file-organization.md) - Small files, clear purpose
- [ADR 007: Naming Conventions](docs/decisions/007-naming-conventions.md) - Consistency prevents bugs

---

## Architecture

### High-Level Design

Scanshelf uses a **Stage abstraction pattern** for composable, resumable, testable pipeline processing:

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

See [Stage Abstraction](docs/architecture/stage-abstraction.md) and ADRs for detailed design philosophy.

### Pipeline Flow

```
PDF → Split Pages → [Tesseract OR OlmOCR] → Find ToC → Extract ToC
```

**Stages:**
- **tesseract** - Local Tesseract OCR (free, fast, paragraph-level) → `tesseract/page_*.json`
- **ocr-pages** - OlmOCR vision API (paid, accurate, paragraph-level) → `ocr-pages/page_*.json`
- **find-toc** - Vision LLM locates ToC pages → `find-toc/finder_result.json`
- **extract-toc** - Multi-phase ToC extraction → `extract-toc/toc.json`

Each stage:
- Validates inputs in `before()` hook
- Processes pages in `run()` hook (controls own parallelization)
- Tracks costs, timing, and metrics via MetricsManager
- Resumes automatically from progress if interrupted (ADR 001)

### Storage Structure

```
~/Documents/book_scans/
├── .library.json             # Library-wide operational state (shuffle orders)
├── {scan-id}/                # Per-book directory (BookStorage)
│   ├── metadata.json         # Book metadata (title, author, year, etc.)
│   ├── source/               # Original page images
│   ├── tesseract/            # Tesseract OCR outputs
│   │   ├── page_NNNN.json    # TesseractPageOutput schema
│   │   ├── metrics.json      # Progress tracking and timing
│   │   └── logs/
│   ├── ocr-pages/            # OlmOCR outputs
│   │   ├── page_NNNN.json    # OcrPagesPageOutput schema
│   │   ├── metrics.json      # Progress tracking, cost, timing
│   │   └── logs/
│   ├── find-toc/             # ToC finder outputs
│   │   ├── finder_result.json # ToC page range detection
│   │   ├── metrics.json
│   │   └── logs/
│   └── extract-toc/          # ToC extractor outputs
│       ├── structure.json    # ToC structure observations
│       ├── toc_unchecked.json # Raw ToC entries
│       ├── toc_diff.json     # Validation and corrections
│       ├── toc.json          # Final ToC output
│       ├── metrics.json
│       └── logs/
```

**Key points:**
- Filesystem is source of truth (ADR 001)
- Each stage has independent metrics and logs
- Schemas enforce type safety at boundaries
- MetricsManager provides atomic progress tracking
- Resume from disk state, not in-memory state

See [Storage System](docs/architecture/storage-system.md) for three-tier design details.

---

**Powered by Claude Sonnet 4.5, Tesseract OCR, and OlmOCR**
