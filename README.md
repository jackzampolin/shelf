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
uv run python ar.py --help
```

---

## Usage

### Library Management

```bash
# Add a book to the library
uv run python ar.py library add ~/Documents/Scans/book-*.pdf

# View all books
uv run python ar.py library list

# Show detailed book information
uv run python ar.py library show <scan-id>

# Check processing status
uv run python ar.py status <scan-id>

# Delete a book
uv run python ar.py library delete <scan-id>
```

### Processing Pipeline

The pipeline processes books through these stages:

```bash
# Stage 1: OCR - Extract text and images via Tesseract
uv run python ar.py process ocr <scan-id>

# Metadata Extraction - Extract title, author, ISBN, etc. from first pages
# (Currently standalone tool - needs CLI integration)
uv run python tools/extract_metadata.py <scan-id>

# Stage 2: Correction - Vision-based OCR error correction
uv run python ar.py process correct <scan-id> --workers 30

# Stage 3: Label - Extract page numbers and classify content blocks
uv run python ar.py process label <scan-id> --workers 30

# Stage 4: Merge - Combine OCR, corrections, and labels
uv run python ar.py process merge <scan-id>

# Stage 5: Structure - Detect chapters (in development)
uv run python ar.py process structure <scan-id>
```

**Note:** Metadata extraction happens after OCR and before Correction. The extracted metadata (title, author, etc.) is used by the Correction and Label stages for improved accuracy.

### Common Options

```bash
# Resume from checkpoint after interruption
uv run python ar.py process correct <scan-id> --resume

# Override default vision model
uv run python ar.py process correct <scan-id> --model gpt-4o

# Clean a stage to restart
uv run python ar.py process clean correct <scan-id>
```

### Quality Reports

Each stage includes analysis tools:

```bash
# Run correction quality report
uv run python pipeline/2_correction/report.py <scan-id>

# Run label classification report
uv run python pipeline/3_label/report.py <scan-id>
```

---

## Current Status

- ✅ **Stage 1 (OCR):** Complete - Tesseract extraction
- 🚧 **Metadata Extraction:** Tool exists (`tools/extract_metadata.py`), needs CLI integration
- ✅ **Stage 2 (Correction):** Complete - Vision-based error fixing
- ✅ **Stage 3 (Label):** Complete - Page numbers & block classification
- 🚧 **Stage 4 (Merge):** Implemented, needs testing
- ❌ **Stage 5 (Structure):** In development

**Current Focus:** Running quality reports on library books to inform structure stage design

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

- [CLAUDE.md](CLAUDE.md) - AI workflow guide for contributors
- [docs/MCP_SETUP.md](docs/MCP_SETUP.md) - Claude Desktop integration

---

## Architecture

### Pipeline Flow

```
PDF → Split Pages → OCR → Metadata Extraction → Correction → Label → Merge → Structure
```

Each stage:
- Supports checkpoint-based resume after interruption
- Tracks costs and token usage
- Produces quality reports for analysis
- Uses BookStorage API for consistent file operations

### Storage Structure

```
~/Documents/book_scans/
├── library.json              # Book catalog
├── {scan-id}/                # Per-book directory
│   ├── source/               # Original page images
│   ├── ocr/                  # OCR outputs + extracted images
│   ├── corrected/            # Corrected pages
│   ├── labels/               # Page classifications
│   ├── processed/            # Merged pages
│   ├── chapters/             # Chapter structure (future)
│   ├── checkpoints/          # Resume checkpoints
│   ├── logs/                 # Per-stage logs
│   └── metadata.json         # Book metadata
```

---

**Powered by Claude Sonnet 4.5 and Tesseract OCR**
