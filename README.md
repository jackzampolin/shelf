# Aerospace Republic Research Infrastructure

## Overview
Automated research infrastructure for analyzing how US decisions during 1935-1955 created the "Aerospace Republic" - a system that prioritized aerospace dominance and financial hegemony over industrial strength, creating the contradictions that define our current crisis.

## Current Status

**Completed Systems:**
- ✅ Book scanning intake system (`tools/scan.py`)
- ✅ Python environment with `uv` package management
- ✅ Organized batch structure for scanned books
- ✅ OCR pipeline for extracting text from scanned PDFs (`pipeline/ocr.py`)
- ✅ 4-agent LLM correction pipeline (`pipeline/correct.py`)
- ✅ Agent 4 targeted fix system (`pipeline/fix.py`)
- ✅ Review handler for flagged pages (`tools/review.py`)
- ✅ Dual-structure merge system (`pipeline/merge.py`)

**Current Books:**
- 📖 *The Accidental President* by A.J. Baime - 447 pages OCR'd, ~60% LLM corrected
- 📖 *Hap Arnold* - Scanned, ready for processing

**In Progress:**
- 🔄 First book LLM correction pipeline (running)
- 🔄 Quote extraction and analysis tools

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
uv pip install -r pyproject.toml
```

### Book Digitization Pipeline

```bash
# Step 0: Scan intake (as-needed, interactive)
uv run python tools/scan.py

# Step 1: OCR extraction from PDFs
uv run python pipeline/ocr.py <book-slug>

# Step 2: LLM correction pipeline (3-agent system)
uv run python pipeline/correct.py <book-slug>

# Step 3: Fix flagged pages with Agent 4
uv run python pipeline/fix.py <book-slug>

# Step 4: Merge into final dual-structure text
uv run python pipeline/merge.py <book-slug>

# Review tools
uv run python tools/review.py <book-slug> report
```

## Project Structure

```
ar-research/
├── pipeline/          # Sequential processing stages
│   ├── ocr.py        # Stage 1: Tesseract OCR extraction
│   ├── correct.py    # Stage 2: 3-agent LLM correction
│   ├── fix.py        # Stage 3: Agent 4 targeted fixes
│   └── merge.py      # Stage 4: Final text merge
├── tools/            # Supporting utilities
│   ├── scan.py       # Scanner intake workflow
│   └── review.py     # Review flagged pages
└── CLAUDE.md         # AI assistant workflow guidelines
```

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