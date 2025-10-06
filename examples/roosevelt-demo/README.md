# Theodore Roosevelt Autobiography - Demo

This demo shows Scanshelf processing a public domain political biography through the complete pipeline.

## About the Book

**Title:** Theodore Roosevelt: An Autobiography
**Author:** Theodore Roosevelt
**Published:** 1913 by Charles Scribner's Sons
**Pages:** 433 scan pages processed (642 book pages originally)
**Copyright:** Public Domain
**Source:** [Internet Archive](https://archive.org/details/theorooseauto00roosrich)

## Demo Overview

This walkthrough demonstrates:
1. **OCR** - Tesseract extraction from scanned pages
2. **Correction** - LLM-based error correction (3-agent system)
3. **Fix** - Targeted fixes for flagged issues
4. **Structure** - Claude Sonnet 4.5 extracting semantic structure

**Processing Stats (actual 433-page book run):**
- OCR: 5.2 minutes (free, Tesseract)
- Correction: 9.0 minutes ($2.77, gpt-4o-mini with 30 workers)
- Fix: 2.3 minutes ($0.32, Claude Sonnet 4.5)
- Structure: 1.5 minutes ($0.49, Claude Sonnet 4.5)
- **Total: ~18 minutes, $3.58**

## Prerequisites

Before running this demo, complete the Scanshelf setup from the main README:

1. **Install Scanshelf:**
   ```bash
   git clone https://github.com/jackzampolin/scanshelf
   cd scanshelf
   uv venv && source .venv/bin/activate
   uv pip install -e .
   ```

2. **Configure API Key:**
   ```bash
   cp .env.example .env
   # Edit .env and add your OpenRouter API key:
   # OPENROUTER_API_KEY=sk-or-v1-...
   ```

3. **Verify Setup:**
   ```bash
   uv run python ar.py --help
   ```

See the [main README](../../README.md) for full installation instructions.

## Quick Start

### 1. Download the Book

```bash
# Download from Internet Archive
curl -L "https://archive.org/download/theorooseauto00roosrich/theorooseauto00roosrich.pdf" \
  -o ~/Downloads/roosevelt-autobiography.pdf
```

### 2. Add to Library

```bash
# Add book to Scanshelf (with auto-generated ID)
uv run python ar.py add ~/Downloads/roosevelt-autobiography.pdf

# Or specify custom ID:
uv run python ar.py add ~/Downloads/roosevelt-autobiography.pdf --id roosevelt-demo
```

This will:
- Extract metadata from first 10 pages
- Create scan folder
- Register in library

### 3. Process Through Pipeline

```bash
# Process entire book through all stages
uv run python ar.py process roosevelt-autobiography

# This will run:
# 1. OCR (Tesseract) - ~5-10 min
# 2. Correction (gpt-4o-mini) - ~10-15 min
# 3. Fix (Claude Sonnet 4.5) - ~2-5 min
# 4. Structure (Claude Sonnet 4.5) - ~1-2 min
# Total: ~20-30 min, ~$12-15
```

### 4. Explore Results

```bash
# View book info
uv run python ar.py library show roosevelt-demo

# Read structured output
cat ~/Documents/book_scans/roosevelt-demo/structured/archive/full_book.md

# Query via MCP (if configured)
# See docs/MCP_SETUP.md for setup instructions
```

## What You'll Get

After processing, you'll have:

```
~/Documents/book_scans/roosevelt-demo/
├── source/              # Original PDF
├── ocr/                 # Raw OCR output
├── corrected/           # LLM-corrected pages
└── structured/          # Semantic outputs
    ├── reading/         # TTS-optimized clean text
    ├── data/           # RAG-ready JSON
    │   ├── body/       # Chapter files
    │   ├── notes/      # Footnotes
    │   └── bibliography/ # Bibliography
    └── archive/        # Complete markdown
```

## Sample Output

See the `output/` directory in this demo for example processed pages showing:
- Chapter extraction
- Footnote parsing
- Clean markdown formatting
- JSON structure for RAG

## Next Steps

- **Audiobooks**: Use `structured/reading/*.md` as TTS input
- **Research**: Query via MCP integration with Claude Desktop
- **RAG**: Use `structured/data/` JSON files for vector embeddings
- **Full book**: Remove `--start` and `--end` flags to process all 642 pages

## Cost Breakdown

**Per-page costs (using default models):**
- OCR: Free (Tesseract)
- Correction: ~$0.02/page (gpt-4o-mini, 3 agents)
- Fix: ~$0.01/page if needed (Claude Sonnet 4.5)
- Structure: ~$0.002/page (Claude Sonnet 4.5)

**433 pages (actual run):** $3.58 total
- $2.77 correction (gpt-4o-mini)
- $0.32 fix (Claude Sonnet 4.5)
- $0.49 structure (Claude Sonnet 4.5)

## Technical Details

**Models Used:**
- Correction: `openai/gpt-4o-mini` (configurable)
- Fix: `anthropic/claude-sonnet-4.5`
- Structure: `anthropic/claude-sonnet-4.5`

**Pipeline Stages:**
1. **OCR** - Layout-aware Tesseract extraction
2. **Correction** - 3-agent XML-structured prompts
   - Agent 1: Detect OCR errors
   - Agent 2: Apply corrections
   - Agent 3: Verify + flag issues
3. **Fix** - Agent 4 targeted fixes for flagged pages
4. **Structure** - Semantic analysis with Claude Sonnet 4.5
   - Chapter boundaries
   - Footnote extraction
   - Bibliography parsing
   - Clean markdown generation

---

**Built with Claude Sonnet 4.5** for intelligent document understanding.
