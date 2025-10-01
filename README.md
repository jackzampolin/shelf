# AR Research - Book Processing Pipeline

Automated pipeline for processing scanned books through OCR, LLM-based error correction, and semantic structuring.

## Quick Start

```bash
# Clone repo
git clone <repo-url>
cd ar-research

# Setup Python environment
uv venv
source .venv/bin/activate
uv pip install -e .

# Configure API keys
cp .env.example .env
# Edit .env with your OpenRouter API key

# Verify installation
ar --help
```

## Happy Path Workflow

### 1. Place PDFs in ~/Documents/Scans

```bash
# Put your scanned book PDFs here
ls ~/Documents/Scans/
# fiery-peace-1.pdf
# fiery-peace-2.pdf
# ...
```

### 2. Ingest Books into Library

```bash
# Smart ingestion with LLM metadata extraction
ar library ingest ~/Documents/Scans/*.pdf

# This will:
# - Analyze first 10 pages with vision LLM
# - Extract title, author, metadata
# - Create scan folder with random ID (e.g., "modest-lovelace")
# - Register in library.json
```

### 3. Run Full Pipeline

```bash
# Process entire book through all 4 stages
ar pipeline <scan-id>

# Stages:
# 1. OCR - Tesseract extraction
# 2. Correct - 3-agent LLM error correction
# 3. Fix - Agent 4 targeted fixes
# 4. Structure - Semantic chapter/chunk extraction
```

### 4. Query Results

```bash
# View library
ar library list
ar library show <scan-id>

# Read structured output
cat ~/Documents/book_scans/<scan-id>/structured/archive/full_book.md

# Search chapters
grep -r "keyword" ~/Documents/book_scans/<scan-id>/structured/data/body/
```

## Other Operations

### Library Management

```bash
# List all books
ar library list

# Show collection stats
ar library stats

# Show scan details
ar library show <scan-id>

# Discover available PDFs
ar library discover ~/Documents/Scans
```

### Run Individual Pipeline Stages

```bash
# Run stages separately
ar ocr <scan-id>           # Stage 1: OCR extraction
ar correct <scan-id>       # Stage 2: 3-agent correction
ar fix <scan-id>           # Stage 3: Agent 4 fixes
ar structure <scan-id>     # Stage 4: Semantic structuring
```

### Monitor Progress

```bash
# Real-time monitoring with ETA
ar monitor <scan-id>

# Quick status check
ar status <scan-id>
```

### Review Flagged Pages

```bash
# Generate review report
ar review <scan-id> report

# Create markdown checklist
ar review <scan-id> checklist
```

## What You Get

After processing, each book has structured outputs:

```
~/Documents/book_scans/<scan-id>/
├── source/                # Original PDFs
├── ocr/                   # Raw OCR output
├── corrected/             # LLM-corrected pages
└── structured/            # Semantic outputs
    ├── reading/           # TTS-optimized clean text
    ├── data/              # RAG-ready JSON (chapters, notes, bibliography)
    └── archive/           # Complete markdown
```

See **[docs/structure_schema.md](docs/structure_schema.md)** for detailed output format.

## Pipeline Details

**4-Stage Processing:**
1. **OCR** - Tesseract with layout detection (free)
2. **Correct** - 3-agent LLM system with XML-structured prompts (~$10/book)
   - Agent 1: Detect OCR errors
   - Agent 2: Apply corrections
   - Agent 3: Verify + flag issues
3. **Fix** - Agent 4 targeted fixes for flagged pages (~$1/book)
4. **Structure** - Semantic chapter/chunk extraction with Claude (~$0.50/book)

**Total cost:** ~$11-12 per 450-page book

**Key Features:**
- Checkpoint system for resumable processing
- Parallel processing with rate limiting
- Atomic library updates for consistency
- XML-structured prompts for better LLM adherence

## Claude Desktop Integration

Query books directly from Claude Desktop using the MCP server.

See **[docs/MCP_SETUP.md](docs/MCP_SETUP.md)** for setup instructions.

## Configuration

All configuration via `.env` file:

```bash
# Required
OPENROUTER_API_KEY=sk-...

# Optional
BOOK_STORAGE_ROOT=~/Documents/book_scans  # Default storage location
CORRECTION_MODEL=openai/gpt-4o-mini       # Correction model
FIX_MODEL=anthropic/claude-3.5-sonnet     # Fix model
STRUCTURE_MODEL=anthropic/claude-sonnet-4.5  # Structure model
```

## Thesis Context

This infrastructure supports research on how US decisions during 1935-1955 created the "Aerospace Republic" - a system prioritizing aerospace dominance and financial hegemony over industrial strength.

**Key Research Questions:**
- How did choosing Europe over Asia doom American manufacturing?
- What warnings were ignored from MacArthur and the China Lobby?
- How did Bretton Woods hollow out industrial capacity?
- What alternative paths existed at decision points?

---

*Built for systematic historical analysis with modern LLM infrastructure.*
