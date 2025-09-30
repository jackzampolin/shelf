# Aerospace Republic Research Infrastructure

## Overview
Automated research infrastructure for analyzing how US decisions during 1935-1955 created the "Aerospace Republic" - a system that prioritized aerospace dominance and financial hegemony over industrial strength, creating the contradictions that define our current crisis.

## Current Status

**Completed Systems:**
- ✅ Unified CLI (`ar.py`) - Single entry point for all operations
- ✅ Library tracking system with LLM-powered book discovery
- ✅ Random identifier system for scan folders (Docker-style naming)
- ✅ 4-stage pipeline: OCR → Correct → Fix → Structure
- ✅ 3-agent LLM correction pipeline with parallel processing
- ✅ Agent 4 targeted fix system for low-confidence pages
- ✅ Real-time progress monitoring with ETA
- ✅ Centralized configuration via `.env` file
- ✅ **MCP Server for Claude Desktop** - Query books directly from Claude chat
- ✅ **Semantic chunking** - RAG-ready ~5-page segments with provenance

**Current Books:**
- 📖 *The Accidental President* by A.J. Baime (scan: `modest-lovelace`)
  - 447 pages fully processed through all 4 stages
  - 5 chapters, 36 semantic chunks
  - Total cost: ~$12

See [GitHub Issues](../../issues) for detailed planning and roadmap.

## Quick Start

### Setup Environment
```bash
# Clone and setup
git clone <repo-url>
cd ar-research

# Setup Python environment
uv venv
source .venv/bin/activate
uv pip install -e .

# Configure environment
cp .env.example .env
# Edit .env with your OpenRouter API key
```

### Library Management

```bash
# View your collection
ar library list                    # List all books
ar library stats                   # Collection statistics
ar library show <scan-id>          # Show scan details

# Add new books
ar library discover ~/Downloads    # Find PDFs, extract metadata with LLM
ar library migrate <folder-name>   # Migrate existing folders to new naming
```

### Book Processing Pipeline

```bash
# Run complete pipeline (all 4 stages)
ar pipeline <scan-id>

# Or run stages individually
ar ocr <scan-id>                   # Step 1: OCR extraction
ar correct <scan-id>               # Step 2: 3-agent LLM correction
ar fix <scan-id>                   # Step 3: Agent 4 targeted fixes
ar structure <scan-id>             # Step 4: Chapter/chunk structuring

# Monitor progress
ar monitor <scan-id>               # Real-time progress with ETA
ar status <scan-id>                # Quick status check

# Review flagged pages
ar review <scan-id> report         # Generate review report
ar review <scan-id> checklist      # Create markdown checklist
```

### Interactive Scan Intake

```bash
ar scan                            # Interactive workflow for new scans
```

### Querying Books

Once books are processed through the full pipeline, you can query them in multiple ways:

#### Option 1: MCP Server (Claude Desktop Integration)

The MCP server provides direct access to your book library from Claude Desktop:

```bash
# Install MCP support
uv pip install -e .

# Configure Claude Desktop (see docs/MCP_SETUP.md)
# Then query naturally in Claude chat:
# "What books do you have in the AR research library?"
# "Search for mentions of Truman in modest-lovelace"
# "Show me chapter 3 from The Accidental President"
```

**MCP Tools Available:**
- `list_books` - List all books with metadata
- `search_book` - Full-text search with context
- `get_chapter` - Retrieve complete chapters
- `get_chunk` - Get semantic chunks for RAG
- `get_chunk_context` - Chunks with surrounding context
- `list_chapters` - Chapter metadata
- `list_chunks` - Chunk summaries

See **[docs/MCP_SETUP.md](docs/MCP_SETUP.md)** for detailed setup instructions.

#### Option 2: Direct File Access

Books are stored as structured JSON files:

```bash
# View book structure
cat ~/Documents/book_scans/<scan-id>/structured/metadata.json

# Read a specific chapter
cat ~/Documents/book_scans/<scan-id>/structured/chapters/chapter_01.md

# Search across chunks
grep -r "keyword" ~/Documents/book_scans/<scan-id>/structured/chunks/

# Get full book as markdown
cat ~/Documents/book_scans/<scan-id>/structured/full_book.md
```

#### Option 3: Python API

Import the library module directly:

```python
from tools.library import LibraryIndex

library = LibraryIndex()

# List all books
books = library.list_all_books()

# Get book info
scan_info = library.get_scan_info('modest-lovelace')

# Read structured data
import json
from pathlib import Path

scan_id = 'modest-lovelace'
chunks_dir = Path.home() / 'Documents' / 'book_scans' / scan_id / 'structured' / 'chunks'

# Load all chunks
for chunk_file in sorted(chunks_dir.glob('chunk_*.json')):
    with open(chunk_file) as f:
        chunk = json.load(f)
        print(f"Chunk {chunk['chunk_id']}: {chunk['text'][:100]}...")
```

## Project Structure

```
ar-research/
├── ar.py              # Unified CLI entry point
├── mcp_server.py      # MCP server for Claude Desktop integration
├── config.py          # Centralized configuration from .env
├── utils.py           # Shared utilities (metadata tracking)
├── pipeline/          # Sequential processing stages
│   ├── run.py        # Pipeline orchestrator
│   ├── ocr.py        # Stage 1: Tesseract OCR extraction
│   ├── correct.py    # Stage 2: 3-agent LLM correction
│   ├── fix.py        # Stage 3: Agent 4 targeted fixes
│   ├── merge.py      # Merge corrected pages for structuring
│   └── structure.py  # Stage 4: Chapter/chunk structuring
├── tools/             # Supporting utilities
│   ├── scan.py       # Scanner intake workflow
│   ├── monitor.py    # Real-time progress monitoring
│   ├── review.py     # Review flagged pages
│   ├── library.py    # Library catalog management
│   ├── ingest.py     # Smart book ingestion with LLM
│   ├── discover.py   # LLM-powered book metadata extraction
│   └── names.py      # Random identifier generation
├── docs/              # Documentation
│   └── MCP_SETUP.md  # MCP server setup guide
├── CLAUDE.md          # AI assistant workflow guidelines
└── README.md          # This file
```

### Book Database Structure

**Collection Level:**
```
~/Documents/book_scans/
├── library.json              # Collection catalog (single source of truth)
└── <scan-id>/                # Random identifier (e.g., "modest-lovelace")
    ├── metadata.json         # Scan-specific processing history
    ├── source/               # Original scanned materials
    ├── ocr/                  # OCR output (page_*.json files, flat)
    ├── corrected/            # LLM-corrected pages (page_*.json files, flat)
    ├── structured/           # Semantic structure for database ingestion
    │   ├── chapters/         # Chapter JSON and markdown files
    │   ├── chunks/           # ~5-page semantic chunks for RAG
    │   ├── full_book.md      # Complete book in markdown
    │   └── metadata.json
    ├── images/               # Extracted images from pages
    ├── needs_review/         # Pages flagged by Agent 3
    └── logs/                 # Pipeline logs and debug files
        ├── debug/            # JSON parsing error logs
        └── reports/          # Processing reports
```

**library.json Structure:**
```json
{
  "version": "1.0",
  "books": {
    "the-accidental-president": {
      "title": "The Accidental President",
      "author": "A.J. Baime",
      "isbn": "978-0544617247",
      "scans": [
        {
          "scan_id": "modest-lovelace",
          "date_added": "2025-09-30",
          "status": "complete",
          "pages": 447,
          "cost_usd": 12.45,
          "models": {
            "ocr": "tesseract",
            "correct": "openai/gpt-4o-mini",
            "fix": "anthropic/claude-3.5-sonnet",
            "structure": "anthropic/claude-sonnet-4.5"
          }
        }
      ]
    }
  },
  "stats": {
    "total_books": 1,
    "total_scans": 1,
    "total_pages": 447,
    "total_cost_usd": 12.45
  }
}
```

**Key Design Principles:**
- **Random identifiers**: Scan folders use Docker-style names (e.g., `modest-lovelace`)
- **Catalog-based**: `library.json` maps identifiers to books and tracks all metadata
- **Multiple scans**: Same book can have multiple scans for LLM comparison
- **Flat page structure**: No batch subdirectories - all pages at root level
- **Single source of truth**: `corrected/` contains best version (Agent 4 overwrites in place)
- **Agent visibility**: All agent outputs (1-4) stored in each page JSON's `llm_processing` section
- **Layered semantics**: Pages (provenance) → Chapters (human reading) → Chunks (LLM queries)
- **Pipeline stages**: source → ocr → corrected → structured → database

## Key Thesis
Between 1935-1955, American leaders made four fateful decisions:
- Lost China as an ally despite clear warnings
- Created Bretton Woods prioritizing financial over industrial strength  
- Systematically suppressed dissenting thought
- Built a secret, unaccountable security state

These decisions created the "Aerospace Republic" - delivering prosperity but embedding contradictions now reaching crisis.

## Technical Stack
- **Python** - Core automation
- **Internet Archive API** - Free document access
- **Scribd/JSTOR** - Commercial biography access
- **Claude/LLM** - Complex document analysis
- **Git/Markdown** - Version control and notes

## Cost Estimate
- **Minimal**: $50/month (Scribd + occasional purchases)
- **Optimal**: $150/month (multiple services + books)
- **Total Project**: ~$1800 over 6 months

## Research Questions
1. How did the choice of Europe over Asia doom American manufacturing?
2. What warnings did MacArthur and the China Lobby give that were ignored?
3. How did financial dominance through Bretton Woods hollow out industry?
4. What alternative paths were available at key decision points?

## Contact
[Your contact info]

---

*"The untold story centers on suppressed alternatives and forgotten warnings that might offer paths forward for our own moment of transformation."*