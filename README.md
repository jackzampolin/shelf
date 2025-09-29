# Aerospace Republic Research Infrastructure

## Overview
Automated research infrastructure for analyzing how US decisions during 1935-1955 created the "Aerospace Republic" - a system that prioritized aerospace dominance and financial hegemony over industrial strength, creating the contradictions that define our current crisis.

## Current Status

**Working Systems:**
- ✅ Book scanning intake system (`scan_intake.py`)
- ✅ Python environment with `uv` package management
- ✅ Organized batch structure for scanned books

**In Progress:**
- 🔄 OCR pipeline for extracting text from scanned PDFs
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

### Scanning Books
```bash
# Interactive mode
python scan_intake.py

# See workflow guide
cat SCAN_WORKFLOW.md
```

## Core Documentation

- **[SCAN_WORKFLOW.md](SCAN_WORKFLOW.md)** - Complete guide to scanning and organizing books
- **[BOOK_OCR.md](BOOK_OCR.md)** - OCR processing pipeline (in development)
- **[CLAUDE.md](CLAUDE.md)** - AI assistant workflow and guidelines

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