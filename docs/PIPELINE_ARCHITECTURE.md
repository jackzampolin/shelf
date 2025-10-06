# Pipeline Architecture

## Overview

The Scanshelf pipeline transforms scanned book PDFs into structured, corrected text through four main stages. Each stage builds on the previous one, progressively refining the text while maintaining a consistent region-based data model.

## Core Principle: Region-Based Corrections

**Key Insight:** Corrections and fixes are applied to individual OCR regions, not to flat text. This allows us to:
1. Filter out headers/footers by region type
2. Preserve OCR structure (reading order, region types)
3. Apply corrections incrementally without losing context
4. Extract clean body text for the structure stage

## Data Transformation Through Pipeline

### Stage 1: OCR

**Input:** PDF page image
**Output:** `ocr/page_0100.json`

**What it does:**
- Extracts text using Tesseract OCR
- Identifies regions (header, body, footer, etc.)
- Assigns reading order to regions
- Creates initial page JSON with raw OCR text

**Example Output:**
```json
{
  "page_number": 100,
  "regions": [
    {
      "type": "header",
      "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY",
      "confidence": 0.95,
      "reading_order": 1
    },
    {
      "type": "body",
      "text": "Instead of opposing the bill I ardontly championed it. Tt was a poorly drawn measure...",
      "confidence": 0.92,
      "reading_order": 2
    }
  ]
}
```

**Note:**
- Region text has OCR errors: "ardontly" → should be "ardently", "Tt" → should be "It"
- Header region will be filtered out later

### Stage 2: Correction (3-Agent Pipeline)

**Input:** `ocr/page_0100.json`
**Output:** `corrected/page_0100.json`

**What it does:**
1. **Agent 1**: Detects OCR errors, creates error catalog
2. **Agent 2**: Applies corrections, returns text with `[CORRECTED:id]` markers
3. **Agent 3**: Verifies corrections, flags issues for review
4. **Region Update**: Parses markers and updates individual regions

**Example Output:**
```json
{
  "page_number": 100,
  "regions": [
    {
      "type": "header",
      "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY",
      "confidence": 0.95,
      "reading_order": 1,
      "corrected": false
    },
    {
      "type": "body",
      "text": "Instead of opposing the bill I ardently[CORRECTED:1] championed it. Tt[CORRECTED:2] was a poorly drawn measure...",
      "confidence": 0.92,
      "reading_order": 2,
      "corrected": true
    }
  ],
  "llm_processing": {
    "error_catalog": {
      "total_errors_found": 2,
      "errors": [
        {"error_id": 1, "original_text": "ardontly", "error_type": "ocr_substitution"},
        {"error_id": 2, "original_text": "Tt", "error_type": "obvious_typo"}
      ]
    },
    "corrected_text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY\n\nInstead of opposing the bill I ardently[CORRECTED:1] championed it. Tt[CORRECTED:2] was...",
    "verification": {
      "confidence_score": 0.7,
      "needs_human_review": true,
      "missed_corrections": [{"error_id": 2, "should_be": "It"}]
    }
  }
}
```

**What changed:**
- Body region text updated with corrections and markers
- Region marked `corrected: true`
- Header region unchanged (will be filtered later)
- `llm_processing` added with full pipeline metadata

**Note:** Some corrections may be imperfect (e.g., "Tt" not fully fixed). That's what the fix stage is for.

**Code:** `pipeline/correct.py:552` - `apply_corrections_to_regions()`

### Stage 3: Fix (Agent 4)

**Input:** Pages flagged in `needs_review/` (subset of pages with low confidence)
**Output:** Updated `corrected/page_0100.json` (overwrites)

**What it does:**
1. **Agent 4**: Reads Agent 3's feedback, makes targeted fixes
2. **Region Update**: Parses `[FIXED:A4-id]` markers and updates regions

**Example Output:**
```json
{
  "page_number": 100,
  "regions": [
    {
      "type": "header",
      "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY",
      "confidence": 0.95,
      "reading_order": 1
    },
    {
      "type": "body",
      "text": "Instead of opposing the bill I ardently[CORRECTED:1] championed it. It[FIXED:A4-1] was a poorly drawn measure...",
      "confidence": 0.92,
      "reading_order": 2,
      "corrected": true,
      "fixed": true
    }
  ],
  "llm_processing": {
    "error_catalog": { /* ... */ },
    "corrected_text": "...",
    "verification": { /* ... */ },
    "agent4_fixes": {
      "timestamp": "2025-10-06T12:45:00",
      "missed_corrections": [
        {"original_text": "Tt", "should_be": "It"}
      ],
      "fixed_text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY\n\nInstead of opposing the bill I ardently[CORRECTED:1] championed it. It[FIXED:A4-1] was..."
    }
  }
}
```

**What changed:**
- "Tt" → "It" with `[FIXED:A4-1]` marker
- Region marked `fixed: true`
- `agent4_fixes` section added to `llm_processing`

**Note:** Only pages flagged by Agent 3 go through this stage. High-confidence pages skip it.

**Code:** `pipeline/fix.py:212` - `apply_fixes_to_regions()`

### Stage 4: Structure

**Input:** All `corrected/page_*.json` files
**Output:** `structured/chapters/`, `structured/chunks/`, `structured/full_book.md`

**What it does:**
1. **Load & Filter**: Extract body regions only, remove markers
2. **Detect Chapters**: Use LLM to find chapter boundaries
3. **Create Chunks**: Split into ~5-page semantic chunks
4. **Generate Output**: Markdown files for reading

**Example: Loading Page 100**

From this JSON:
```json
{
  "regions": [
    {"type": "header", "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY"},
    {"type": "body", "text": "Instead of opposing... It[FIXED:A4-1] was...", "corrected": true, "fixed": true}
  ]
}
```

Structure loader extracts:
```
"Instead of opposing the bill I ardently championed it. It was a poorly drawn measure..."
```

**What changed:**
- Header region filtered out (type != body)
- Body region text extracted
- Markers removed (`[CORRECTED:1]`, `[FIXED:A4-1]`)
- Clean corrected text ready for reading

**Final Output Example** (`structured/full_book.md`):
```markdown
# Theodore Roosevelt: An Autobiography

## Chapter 1: Boyhood and Youth

Instead of opposing the bill I ardently championed it. It was a poorly
drawn measure, and the Governor, Grover Cleveland, was at first doubtful
about signing it...
```

**Code:** `pipeline/structure/loader.py:37` - `extract_body_text()`

## Summary: Data Flow

```
┌─────────────┐
│  PDF Page   │
└──────┬──────┘
       │
   ┌───▼───┐ Stage 1: OCR
   │  OCR  │ ─────────────────────────────────────
   └───┬───┘ Creates regions with raw OCR text
       │     Errors: "ardontly", "Tt"
       │
┌──────▼──────────┐
│ ocr/page_*.json │ regions[].text = "ardontly... Tt was..."
└──────┬──────────┘
       │
  ┌────▼────┐ Stage 2: Correction
  │ Agent 1 │ ─────────────────────────────────────
  │ Agent 2 │ Detects + corrects errors
  │ Agent 3 │ Updates regions with corrections
  └────┬────┘ Markers: [CORRECTED:id]
       │
┌──────▼────────────────┐
│ corrected/page_*.json │ regions[].text = "ardently[CORRECTED:1]... Tt[CORRECTED:2] was..."
└──────┬────────────────┘ regions[].corrected = true
       │
  ┌────▼────┐ Stage 3: Fix (if flagged)
  │ Agent 4 │ ─────────────────────────────────────
  └────┬────┘ Targeted fixes for missed corrections
       │     Markers: [FIXED:A4-id]
       │
┌──────▼────────────────┐
│ corrected/page_*.json │ regions[].text = "ardently[CORRECTED:1]... It[FIXED:A4-1] was..."
└──────┬────────────────┘ regions[].fixed = true
       │
  ┌────▼─────┐ Stage 4: Structure
  │  Loader  │ ─────────────────────────────────────
  │ Detector │ Extract body regions (exclude headers)
  │ Chunker  │ Remove markers, create chapters/chunks
  └────┬─────┘
       │
┌──────▼──────────────┐
│ structured/*.md     │ Clean corrected text
│ structured/*.json   │ No headers, no markers
└─────────────────────┘ "ardently... It was..."
```

## Why Region-Based Architecture?

**The Problem:**
- OCR creates structured regions (header, body, footer)
- LLMs return flat text with corrections
- How do we keep corrections AND filter headers?

**The Solution:**
Parse LLM output markers and apply corrections back to individual regions. This lets us:
- Filter by region type (exclude headers/footers)
- Use corrected text (not raw OCR)
- Track what changed (markers show provenance)

**Benefits:**
1. Headers excluded automatically (filter by `type`)
2. Corrections preserved (applied to regions)
3. Debugging easy (`llm_processing` has full text)
4. Future-proof (enables per-paragraph features)

## Implementation Checklist

When adding a new correction/fix stage:

- [ ] Parse output for markers (`[CORRECTED:id]`, `[FIXED:A4-id]`, etc.)
- [ ] Create mapping of error_id → {original, corrected}
- [ ] Iterate through regions
- [ ] Apply changes to regions that contain the original text
- [ ] Mark regions as updated (`corrected: true`, `fixed: true`, etc.)
- [ ] Save updated page JSON

See `pipeline/correct.py:552` or `pipeline/fix.py:212` for reference implementations.

## Common Mistakes

1. ❌ **Falling back to full_text** - Contains headers. Always use regions.
2. ❌ **Only updating llm_processing** - Structure stage won't see it. Update regions.
3. ❌ **Skipping marker parsing** - Can't update regions without parsing markers.
4. ❌ **Overwriting regions** - Preserves nothing. Always update in place.

## Testing

```bash
# Run stage on single page
uv run python ar.py correct book-id --start 100 --end 100

# Verify regions updated
python3 -c "import json; \
  d=json.load(open('path/page_0100.json')); \
  body=next(r for r in d['regions'] if r['type']=='body'); \
  print('Corrected:', body.get('corrected', False)); \
  print('Has markers:', '[CORRECTED:' in body['text'])"
```

---

**Related Docs:**
- `CLAUDE.md` - General workflow and conventions
