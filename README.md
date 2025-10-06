# Scanshelf - Turn Physical Books into Digital Libraries

Automated pipeline for processing scanned books into structured, searchable digital libraries. Built for researchers, audiobook creators, and anyone who wants AI-powered access to physical book collections.

**Use Cases:**
- 📚 **Research Libraries** - Convert book scans into queryable knowledge bases
- 🎧 **Audiobook Creation** - Generate TTS-ready markdown from scans (future: direct TTS integration)
- 🤖 **AI Chat** - Query books with Claude via MCP integration
- 🔍 **Full-Text Search** - Semantic chunking for RAG applications

## Quick Start

```bash
# Clone repo
git clone https://github.com/jackzampolin/scanshelf
cd scanshelf

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

### 2. Add Books to Library

```bash
# Add book(s) with automatic metadata extraction
ar add ~/Documents/Scans/accidental-president-*.pdf

# This will:
# - Analyze first 10 pages with vision LLM
# - Extract title, author, metadata
# - Create scan folder with slugified ID (e.g., "accidental-president")
# - Combine multi-part PDFs automatically
# - Register in library.json

# Or specify custom ID:
ar add ~/Documents/Scans/*.pdf --id my-custom-name
```

### 3. Process Books

```bash
# Process entire book through all 4 stages
ar process <scan-id>

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
# Quick status check
ar status <scan-id>

# Live monitoring with real-time updates
ar status <scan-id> --watch
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

---

**Powered by Claude Sonnet 4.5** for intelligent document understanding and structure extraction.
