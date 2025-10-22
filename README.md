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

- [CLAUDE.md](CLAUDE.md) - AI workflow guide for contributors
- [docs/MCP_SETUP.md](docs/MCP_SETUP.md) - Claude Desktop integration

---

## Architecture

### Pipeline Flow

```
PDF → Split Pages → OCR → Correction → Label → Merge → Structure (TBD)
```

Each stage:
- Inherits from BaseStage (before/run/after lifecycle)
- Automatically resumes from checkpoints if interrupted
- Tracks costs and token usage
- Generates quality reports in after() hook
- Uses BookStorage and StageStorage APIs for consistent file operations

### Storage Structure

```
~/Documents/book_scans/
├── library.json              # Book catalog (LibraryStorage)
├── {scan-id}/                # Per-book directory (BookStorage)
│   ├── source/               # Original page images
│   ├── ocr/                  # OCR outputs (stage: "ocr")
│   │   ├── page_NNNN.json    # OCR text blocks
│   │   └── checkpoint.json   # Resume state
│   ├── corrected/            # Corrected pages (stage: "corrected")
│   │   ├── page_NNNN.json    # Corrected text
│   │   └── checkpoint.json
│   ├── labels/               # Page classifications (stage: "labels")
│   │   ├── page_NNNN.json    # Block classifications + page numbers
│   │   └── checkpoint.json
│   ├── merged/               # Merged pages (stage: "merged")
│   │   ├── page_NNNN.json    # Three-way merged data
│   │   └── checkpoint.json
│   ├── images/               # Extracted image regions
│   ├── logs/                 # Per-stage logs
│   └── metadata.json         # Book metadata
```

---

**Powered by Claude Sonnet 4.5 and Tesseract OCR**
