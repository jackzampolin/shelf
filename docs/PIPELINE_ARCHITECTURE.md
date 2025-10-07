# Scanshelf Pipeline Architecture

## Overview

The Scanshelf pipeline transforms scanned book PDFs into clean, structured text suitable for reading, search, and AI applications. The pipeline has **four stages**:

```
PDF → OCR → Correction → Fix → Structure → Clean Book
```

**Total time:** ~15-20 minutes for 600-page book
**Total cost:** ~$12-15 (primarily LLM API calls)

---

## Architecture Principles

### 1. Region-Based Data Model

**Core Insight:** OCR creates **regions** (header, body, footer, caption, etc.). We apply corrections to individual regions, not flat text. This lets us filter by region type while preserving all corrections.

```
OCR: Creates regions → Correction: Updates regions → Structure: Filters regions
```

**Why?** Enables intelligent filtering (remove headers) without losing corrected content.

### 2. Progressive Enhancement

Each stage builds on the previous, adding value:
- **Stage 1:** Raw OCR with errors
- **Stage 2:** Corrected text (30 workers, parallel)
- **Stage 3:** Targeted fixes for low-confidence pages
- **Stage 4:** Structured output (chapters, chunks, clean text)

### 3. Parallelization

Heavy LLM work is parallelized:
- Correction: 30 workers processing pages
- Fix: Targeted subset only
- Structure: 30 workers processing batches

**Result:** 600-page book processes in 15-20 minutes (not hours!)

### 4. Verification at Every Stage

Multi-agent verification pattern (inspired by OCR stage):
- Agent 1: Does the work
- Agent 2: Verifies quality
- Agent 3: Reconciles conflicts

**Result:** Built-in quality assurance, catches errors early.

---

## Stage Breakdown

### Stages 1-3: OCR and Correction
**See: [`docs/OCR_CLEAN.md`](OCR_CLEAN.md)**

```
PDF → OCR → Correction → Fix → corrected/page_*.json
```

**Output:** Clean, corrected pages with region structure
**Time:** ~12-15 minutes (600 pages)
**Cost:** ~$11

**Key files:**
- `pipeline/ocr.py` - Tesseract OCR with region detection
- `pipeline/correct.py` - 3-agent correction (detect, apply, verify)
- `pipeline/fix.py` - Targeted fixes for flagged pages

### Stage 4: Structure Detection
**See: [`docs/STRUCTURE.md`](STRUCTURE.md)**

```
corrected/*.json → Structure → structured/{reading,data,archive}/
```

**Output:** Three formats (reading, data, archive) + RAG chunks
**Time:** ~3-4 minutes (600 pages)
**Cost:** ~$1.20

**Key files:**
- `pipeline/structure/` - Modular structure detection pipeline
  - Light structure detection (fast, approximate)
  - Sliding window extraction (parallel, verified)
  - Semantic chunking for RAG
  - Multi-format output generation

---

## Data Flow

```
┌──────────────┐
│  input.pdf   │
└──────┬───────┘
       │
       │ Stage 1: OCR (Tesseract)
       │ • Detect regions
       │ • Extract raw text
       ↓
┌──────────────┐
│ ocr/*.json   │ regions[].text = "ardontly... Tt was..."
└──────┬───────┘
       │
       │ Stage 2: Correction (GPT-4o-mini, 30 workers)
       │ • Detect errors
       │ • Apply corrections with markers
       │ • Verify quality
       ↓
┌──────────────┐
│corrected/    │ regions[].text = "ardently[CORRECTED:1]... It[CORRECTED:2]..."
│  *.json      │ regions[].corrected = true
└──────┬───────┘
       │
       │ Stage 3: Fix (Claude, targeted subset)
       │ • Re-process low-confidence pages
       │ • Apply missed corrections
       ↓
┌──────────────┐
│corrected/    │ regions[].text = "ardently[CORRECTED:1]... It[FIXED:A4-1]..."
│  *.json      │ regions[].fixed = true
└──────┬───────┘
       │
       │ Stage 4: Structure (Hybrid approach)
       │ • Light structure detection (Claude)
       │ • Sliding window extraction (GPT-4o-mini, 30 workers)
       │ • Semantic chunking for RAG
       │ • Multi-format generation
       ↓
┌──────────────┐
│ structured/  │ • reading/full_book.txt (TTS-ready)
│              │ • data/chunks/*.json (RAG-ready)
│              │ • archive/full_book.md (human-readable)
└──────────────┘
```

---

## Output Formats

### 1. Reading Text (`structured/reading/`)
**Purpose:** Text-to-speech, audiobook generation

```
reading/
├── full_book.txt         # Clean, chapter-delimited text
├── metadata.json         # Chapter positions, durations
└── page_mapping.json     # Scan page ↔ book page
```

### 2. Structured Data (`structured/data/`)
**Purpose:** RAG, search, analysis

```
data/
├── document_map.json     # Book metadata, structure
├── chunks/
│   └── chunk_*.json     # Semantic chunks (500-1000 words)
├── body/
│   └── chapter_*.json   # Per-chapter with paragraphs
└── back_matter/
    ├── notes.json
    └── bibliography.json
```

**Each chunk has provenance:**
```json
{
  "chunk_id": "ch03_chunk_007",
  "text": "...",
  "scan_pages": [78, 79, 80],      // Link back to PDF
  "book_pages": ["58", "59", "60"]
}
```

### 3. Archive (`structured/archive/`)
**Purpose:** Human reading, preservation

```
archive/
└── full_book.md          # Complete markdown
```

---

## Running the Pipeline

```bash
# Full pipeline (all stages)
ar process <scan-id>

# Individual stages
ar ocr <scan-id>
ar correct <scan-id>
ar fix <scan-id>
ar structure <scan-id>

# Monitor progress
ar status <scan-id> --watch

# Test on page range (where supported)
ar correct <scan-id> --start 100 --end 110
```

---

## Cost Breakdown (600-page book)

| Stage | Model | Workers | Time | Cost |
|-------|-------|---------|------|------|
| OCR | Tesseract | Local | 4-6min | Free |
| Correction | GPT-4o-mini | 30 | 6-8min | ~$10 |
| Fix | Claude Sonnet 4.5 | 10 | 2-3min | ~$1 |
| Structure | Hybrid | 30 | 3-4min | ~$1.20 |
| **Total** | | | **15-20min** | **~$12** |

**Cost per page:** ~$0.02
**Time per page:** ~2 seconds (thanks to parallelization!)

---

## Next Steps

1. **To understand OCR/Correction:** Read [`docs/OCR_CLEAN.md`](OCR_CLEAN.md)
2. **To understand Structure:** Read [`docs/STRUCTURE.md`](STRUCTURE.md)
3. **To run the pipeline:** See [`README.md`](../README.md)
4. **To add a new book:** Use `uv run python ar.py library add <pdf-path>`

---

## Implementation Status

- [x] Stage 1: OCR with region detection
- [x] Stage 2: Correction with 3-agent pattern
- [x] Stage 3: Fix for low-confidence pages
- [x] Stage 4: Structure extraction and assembly
  - [x] Sliding window extractor (3-agent pattern)
  - [x] Batch assembler with overlap reconciliation
  - [x] Semantic chunker for RAG
  - [x] Multi-format generator (reading/data/archive)

**Status:** ✅ All stages complete and validated (92% accuracy on 636-page Roosevelt autobiography)
