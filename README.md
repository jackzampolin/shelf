# Scanshelf - Turn Physical Books into Digital Libraries

A vision-powered OCR pipeline that transforms scanned books into structured, high-quality digital text using Tesseract and multimodal LLMs.

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
uv run python shelf.py book <scan-id> info --stage ocr
uv run python shelf.py book <scan-id> info --json

# Run full pipeline (OCR → Paragraph-Correct → Label-Pages → Extract-ToC)
uv run python shelf.py book <scan-id> process
uv run python shelf.py book <scan-id> process --clean  # Clean all stages first

# Run single stage
uv run python shelf.py book <scan-id> run-stage ocr
uv run python shelf.py book <scan-id> run-stage paragraph-correct --model gpt-4o
uv run python shelf.py book <scan-id> run-stage label-pages --workers 30

# View stage reports (CSV with quality metrics)
uv run python shelf.py book <scan-id> report --stage paragraph-correct
uv run python shelf.py book <scan-id> report --stage label-pages --filter "printed_page_number="
```

**Stages:**
- **ocr** - Extract text and images via Tesseract (3 providers with vision selection)
- **paragraph-correct** - Vision-based OCR error correction with confidence scoring
- **label-pages** - Extract page numbers and classify content blocks (two-stage process)
- **extract_toc** - Find and extract table of contents (phase-based, not page-based)

**Note:** All stages auto-resume from progress if interrupted. Metrics tracked for cost and time.

### Stage Cleanup

```bash
# Clean a stage to restart from scratch
uv run python shelf.py book <scan-id> clean --stage ocr
uv run python shelf.py book <scan-id> clean --stage paragraph-correct --yes  # Skip confirmation
```

### Library-wide Batch Processing

Run stages across all books in your library:

```bash
# Run a stage across all books (persistent random order)
uv run python shelf.py batch paragraph-correct
uv run python shelf.py batch label-pages --model x-ai/grok-vision-beta

# Control processing order
uv run python shelf.py batch paragraph-correct --reshuffle  # Create new random order
uv run python shelf.py batch paragraph-correct --force      # Regenerate completed books

# Customize workers for parallel processing
uv run python shelf.py batch ocr --workers 10
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
- **✏️ Corrections Viewer** - Compare OCR output vs corrected text side-by-side
- **🏷️ Labels Viewer** - View page labels with visual bounding box overlays
- **📊 Stats Viewer** - Aggregate label statistics and confidence metrics

**Features:**
- Side-by-side image and data comparison
- Canvas overlays for bounding boxes with color-coded block types
- HTMX-powered smooth navigation (no full page reloads)
- Responsive design with proper template inheritance

---

## Current Status

- ✅ **OCR Stage:** Complete - Tesseract extraction with 3-provider vision selection
- ✅ **Paragraph-Correct Stage:** Complete - Vision-based OCR error correction with confidence scoring
- ✅ **Label-Pages Stage:** Complete - Two-stage page numbers & block classification
- ✅ **Extract-ToC Stage:** Complete - Phase-based table of contents extraction
- ✅ **CLI Refactor:** Complete - Namespace structure (library/book/batch) with BaseStage abstraction
- ❌ **Structure Stage:** Not yet implemented - will use corrected text + labels

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

### Stage Documentation
- [OCR Stage](pipeline/ocr/README.md) - Tesseract-based text extraction with vision selection
- [Paragraph-Correct Stage](pipeline/paragraph_correct/README.md) - Vision-based error correction
- [Label-Pages Stage](pipeline/label_pages/README.md) - Page numbers and block classification
- [Extract-ToC Stage](pipeline/extract_toc/README.md) - Table of contents extraction

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
- **Resumable** - Metrics-based progress tracking resumes from exact point of interruption
- **Type-safe** - Pydantic schemas validate data at boundaries
- **Cost-aware** - Track every LLM API call financially via MetricsManager
- **Independent** - Stages evolve separately, communicate via files
- **Testable** - Test stages in isolation with mock data

See [Stage Abstraction](docs/architecture/stage-abstraction.md) for detailed design philosophy.

### Pipeline Flow

```
PDF → Split Pages → OCR → Paragraph-Correct → Label-Pages → Extract-ToC → Structure (TBD)
```

**Stages:**
- **OCR** - Tesseract extraction (3 providers, vision selection) → `ocr/page_*.json`
- **Paragraph-Correct** - Vision LLM error correction (I/O-parallel) → `paragraph-correct/page_*.json`
- **Label-Pages** - Page numbers + block classification (two-stage) → `label-pages/page_*.json`
- **Extract-ToC** - Table of contents finder and extractor (phase-based) → `extract_toc/toc.json`
- **Structure** (planned) - Chapter/section extraction using labels + ToC

Each stage:
- Validates inputs in `before()` hook
- Processes pages in `run()` hook (controls own parallelization)
- Generates quality reports (CSV) automatically
- Tracks costs, timing, and metrics via MetricsManager
- Resumes automatically from progress if interrupted

### Storage Structure

```
~/Documents/book_scans/
├── .library.json             # Library-wide operational state (shuffle orders)
├── {scan-id}/                # Per-book directory (BookStorage)
│   ├── metadata.json         # Book metadata (title, author, year, etc.)
│   ├── source/               # Original page images
│   ├── ocr/                  # OCR stage outputs
│   │   ├── page_NNNN.json    # OCRPageOutput schema
│   │   ├── report.csv        # Quality metrics (confidence, blocks)
│   │   ├── .metrics          # Progress tracking (page_metrics source of truth)
│   │   └── logs/
│   │       └── ocr_{timestamp}.jsonl
│   ├── paragraph-correct/    # Paragraph correction stage outputs
│   │   ├── page_NNNN.json    # ParagraphCorrectPageOutput schema
│   │   ├── report.csv        # Quality metrics (corrections, similarity)
│   │   ├── .metrics
│   │   └── logs/
│   ├── label-pages/          # Label-pages stage outputs
│   │   ├── stage1/           # Stage 1: structural analysis outputs
│   │   ├── stage2/           # Stage 2: block classification outputs
│   │   │   └── page_NNNN.json # LabelPagesPageOutput schema
│   │   ├── report.csv        # Quality metrics (classifications)
│   │   ├── .metrics
│   │   └── logs/
│   ├── extract_toc/          # Extract-ToC stage outputs
│   │   ├── finder_result.json # ToC page range detection
│   │   ├── structure.json    # ToC structure observations
│   │   ├── toc_unchecked.json # Raw ToC entries
│   │   ├── toc_diff.json     # Validation and corrections
│   │   ├── toc.json          # Final ToC output
│   │   ├── .metrics
│   │   └── logs/
│   └── images/               # Extracted image regions (from OCR)
```

**Key points:**
- Filesystem is source of truth for books (LibraryStorage scans directories)
- `.library.json` stores operational state (shuffle orders for batch command)
- Each stage has independent metrics (`.metrics`) and logs
- Quality reports (CSV) generated automatically during stage execution
- Schemas enforce type safety at boundaries (output/metrics/report)
- MetricsManager replaced CheckpointManager for progress tracking

See [Storage System](docs/architecture/storage-system.md) for three-tier design details.

---

**Powered by Claude Sonnet 4.5 and Tesseract OCR**
