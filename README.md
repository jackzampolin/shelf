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
# Add a book to the library
uv run python shelf.py add ~/Documents/Scans/book-*.pdf

# View all books
uv run python shelf.py list

# Show detailed book information
uv run python shelf.py show <scan-id>

# Check processing status
uv run python shelf.py status <scan-id>

# View library statistics
uv run python shelf.py stats

# Delete a book
uv run python shelf.py delete <scan-id>
```

### Processing Pipeline

The pipeline processes books through these stages (auto-resumes from checkpoints):

```bash
# Run full pipeline (OCR → Correction → Label → Merge)
uv run python shelf.py process <scan-id>

# Run single stage
uv run python shelf.py process <scan-id> --stage ocr
uv run python shelf.py process <scan-id> --stage corrected
uv run python shelf.py process <scan-id> --stage labels
uv run python shelf.py process <scan-id> --stage merged

# Run multiple stages
uv run python shelf.py process <scan-id> --stages ocr,corrected

# Customize workers and model
uv run python shelf.py process <scan-id> --workers 30 --model gpt-4o
```

**Stages:**
- **ocr** - Extract text and images via Tesseract
- **corrected** - Vision-based OCR error correction
- **labels** - Extract page numbers and classify content blocks
- **merged** - Combine OCR, corrections, and labels

**Note:** Pipeline automatically resumes from checkpoints if interrupted. Quality reports are generated automatically in each stage's `after()` hook.

### Stage Cleanup

```bash
# Clean a stage to restart from scratch
uv run python shelf.py clean <scan-id> --stage ocr
uv run python shelf.py clean <scan-id> --stage corrected -y  # Skip confirmation
```

---

## Current Status

- ✅ **OCR Stage:** Complete - Tesseract extraction with image detection
- ✅ **Correction Stage:** Complete - Vision-based OCR error correction
- ✅ **Label Stage:** Complete - Page numbers & block classification
- ✅ **Merge Stage:** Complete - Three-way merge (OCR + Corrections + Labels)
- 🚧 **CLI Refactor:** New `shelf.py` using BaseStage abstraction and runner.py
- ❌ **Structure Stage:** Not yet implemented - will use merged outputs

**Current Focus:** Testing new CLI and preparing for structure stage design

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
- [OCR Stage](pipeline/ocr/README.md) - Tesseract-based text extraction
- [Correction Stage](pipeline/correction/README.md) - Vision-based error correction
- [Label Stage](pipeline/label/README.md) - Page numbers and block classification
- [Merge Stage](pipeline/merged/README.md) - Three-way data merge

---

## Architecture

### High-Level Design

Scanshelf uses a **Stage abstraction pattern** for composable, resumable, testable pipeline processing:

**Core Components:**
1. **BaseStage** - Three-hook lifecycle (before/run/after) with schema-driven validation
2. **Storage System** - Three-tier hierarchy (Library → Book → Stage)
3. **CheckpointManager** - Atomic progress tracking with filesystem synchronization
4. **PipelineLogger** - Dual-output logging (JSON + human-readable)

**Key Properties:**
- **Resumable** - Checkpoint-based resume from exact point of interruption
- **Type-safe** - Pydantic schemas validate data at boundaries
- **Cost-aware** - Track every LLM API call financially
- **Independent** - Stages evolve separately, communicate via files
- **Testable** - Test stages in isolation with mock data

See [Stage Abstraction](docs/architecture/stage-abstraction.md) for detailed design philosophy.

### Pipeline Flow

```
PDF → Split Pages → OCR → Correction → Label → Merge → Structure (TBD)
```

**Stages:**
- **OCR** - Tesseract extraction (CPU-parallel) → `ocr/page_*.json`
- **Correction** - Vision LLM error fixing (I/O-parallel) → `corrected/page_*.json`
- **Label** - Page numbers + block classification → `labels/page_*.json`
- **Merge** - Three-way deterministic merge → `merged/page_*.json`
- **Structure** (planned) - Chapter/section extraction

Each stage:
- Validates inputs in `before()` hook
- Processes pages in `run()` hook (controls own parallelization)
- Generates quality reports in `after()` hook
- Tracks costs, timing, and metrics per page
- Resumes automatically from checkpoint if interrupted

### Storage Structure

```
~/Documents/book_scans/
├── {scan-id}/                # Per-book directory (BookStorage)
│   ├── metadata.json         # Book metadata (title, author, year, etc.)
│   ├── source/               # Original page images
│   ├── ocr/                  # OCR stage outputs
│   │   ├── page_NNNN.json    # OCRPageOutput schema
│   │   ├── report.csv        # Quality metrics (confidence, blocks)
│   │   ├── .checkpoint       # Progress state (page_metrics source of truth)
│   │   └── logs/
│   │       └── ocr_{timestamp}.jsonl
│   ├── corrected/            # Correction stage outputs
│   │   ├── page_NNNN.json    # CorrectionPageOutput schema
│   │   ├── report.csv        # Quality metrics (corrections, similarity)
│   │   ├── .checkpoint
│   │   └── logs/
│   ├── labels/               # Label stage outputs
│   │   ├── page_NNNN.json    # LabelPageOutput schema
│   │   ├── report.csv        # Quality metrics (classifications)
│   │   ├── .checkpoint
│   │   └── logs/
│   ├── merged/               # Merge stage outputs
│   │   ├── page_NNNN.json    # MergedPageOutput schema
│   │   ├── .checkpoint
│   │   └── logs/
│   └── images/               # Extracted image regions (from OCR)
```

**Key points:**
- No `library.json` - filesystem is source of truth (LibraryStorage scans directories)
- Each stage has independent checkpoint (`.checkpoint`) and logs
- Quality reports (CSV) generated automatically in `after()` hook
- Schemas enforce type safety at boundaries (input/output/checkpoint/report)

See [Storage System](docs/architecture/storage-system.md) for three-tier design details.

---

**Powered by Claude Sonnet 4.5 and Tesseract OCR**
