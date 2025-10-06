# OCR and Text Correction Pipeline

## Overview

Stages 1-3 of the Scanshelf pipeline transform scanned book PDFs into clean, corrected text. Each stage builds on the previous one using a **region-based data model**.

## Core Principle: Regions

OCR creates **regions** - structured blocks of text with types (header, body, footer, etc.). Corrections are applied to individual regions, not flat text. This lets us filter by region type while preserving corrections.

---

## Stage 1: OCR

**Input:** PDF file
**Output:** `ocr/page_*.json` + `images/page_*.png`

**What it does:**
1. Converts PDF to images (one per page)
2. Runs Tesseract OCR on each image
3. Detects regions (header, body, caption, footer, page number)
4. Assigns reading order to regions
5. Saves JSON with raw OCR text in each region

**Example output:**
```json
{
  "page_number": 100,
  "regions": [
    {
      "id": "r0",
      "type": "header",
      "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY",
      "bbox": [100, 50, 500, 80],
      "confidence": 0.95,
      "reading_order": 1
    },
    {
      "id": "r1",
      "type": "body",
      "text": "Instead of opposing the bill I ardontly championed it. Tt was poorly drawn...",
      "bbox": [100, 100, 500, 800],
      "confidence": 0.92,
      "reading_order": 2
    }
  ]
}
```

**What's wrong:** OCR errors in region text ("ardontly" → "ardently", "Tt" → "It")

**Code:** `pipeline/ocr.py`

---

## Stage 2: Correction

**Input:** `ocr/page_*.json`
**Output:** `corrected/page_*.json`

**What it does:**
1. Concatenates correctable regions (header, body, caption, footnote)
   - **Note:** Headers are included because OCR sometimes misclassifies body text as "header" (e.g., chapter endings, large captions at page top)
   - Headers will be filtered out later in the structure stage
2. LLM detects OCR errors, returns error catalog
3. LLM applies corrections, returns text with `[CORRECTED:id]` markers
4. LLM verifies corrections, flags low-confidence pages for review
5. **Parses markers** to find what was corrected
6. **Updates each region** with corrections (including headers)
7. Marks regions as `corrected: true`

**Example output:**
```json
{
  "page_number": 100,
  "regions": [
    {
      "id": "r0",
      "type": "header",
      "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY in question made me feel that, whatever the theories might be, as a matter of practical common sense I could not conscientiously[CORRECTED:1] vote for the continuance...",
      "confidence": 0.95,
      "reading_order": 1,
      "corrected": true
    },
    {
      "id": "r1",
      "type": "body",
      "text": "Instead of opposing the bill I ardently championed it. It[CORRECTED:3] was a poorly drawn measure...",
      "confidence": 0.92,
      "reading_order": 2,
      "corrected": true
    }
  ],
  "llm_processing": {
    "timestamp": "2025-10-06T12:37:00",
    "model": "openai/gpt-4o-mini",
    "error_catalog": {
      "total_errors_found": 2,
      "errors": [
        {"error_id": 1, "original_text": "ardontly", "error_type": "ocr_substitution"},
        {"error_id": 2, "original_text": "Tt", "error_type": "obvious_typo"}
      ]
    },
    "verification": {
      "confidence_score": 0.8,
      "needs_human_review": false
    }
  }
}
```

**Code:** `pipeline/correct.py`

---

## Stage 3: Fix

**Input:** Pages flagged for review (subset with low confidence)
**Output:** Updated `corrected/page_*.json` (overwrites)

**What it does:**
1. Reads verification feedback from correction stage
2. LLM makes targeted fixes for missed/incorrect corrections
3. Returns text with `[FIXED:A4-id]` markers
4. **Parses markers** to find what was fixed
5. **Updates each region** with fixes
6. Marks regions as `fixed: true`

**Example output:**
```json
{
  "page_number": 100,
  "regions": [
    {
      "id": "r0",
      "type": "header",
      "text": "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY",
      "reading_order": 1
    },
    {
      "id": "r1",
      "type": "body",
      "text": "Instead of opposing the bill I ardently[CORRECTED:1] championed it. It[FIXED:A4-1] was poorly drawn...",
      "reading_order": 2,
      "corrected": true,
      "fixed": true
    }
  ],
  "llm_processing": {
    "...": "...",
    "agent4_fixes": {
      "timestamp": "2025-10-06T12:45:00",
      "missed_corrections": [
        {"original_text": "Tt", "should_be": "It"}
      ]
    }
  }
}
```

**Note:** Only pages flagged for review go through this stage (typically 30-50% of total pages).

**Code:** `pipeline/fix.py`

---

## Data Flow Summary

```
PDF
 ↓
[OCR] Creates regions with raw text
 ↓
ocr/page_*.json
regions[].text = "ardontly... Tt was..."
 ↓
[Correction] Updates regions with corrections
 ↓
corrected/page_*.json
regions[].text = "ardently[CORRECTED:1]... It[CORRECTED:2] was..."
regions[].corrected = true
 ↓
[Fix] Updates flagged regions with fixes (subset)
 ↓
corrected/page_*.json (updated)
regions[].text = "ardently[CORRECTED:1]... It[FIXED:A4-1] was..."
regions[].fixed = true
 ↓
Ready for Structure stage (see docs/STRUCTURE.md)
```

---

## Why Regions?

**Problem:** OCR creates typed regions. LLMs return flat text. How do we keep both corrections AND filter headers?

**Solution:** Parse LLM markers and update regions individually.

**Benefits:**
- Filter by type (exclude headers automatically)
- Preserve corrections (in region text)
- Track changes (markers show what changed)
- Enable features (per-paragraph annotations, etc.)

---

## Implementation Pattern

When adding correction/fix logic to a new stage:

1. LLM returns text with `[MARKER:id]` annotations
2. Parse markers to extract what changed
3. Match changes to original regions by text
4. Update region text with correction + marker
5. Mark region as updated (e.g., `corrected: true`)

**Example:** `pipeline/correct.py:552` - `apply_corrections_to_regions()`

---

## Common Mistakes

1. ❌ **Using full_text instead of regions** - Full text includes headers
2. ❌ **Only updating llm_processing** - Structure stage extracts from regions
3. ❌ **Skipping marker parsing** - Can't update regions without parsing
4. ❌ **Overwriting regions** - Update in place to preserve structure

---

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

**Next:** See `docs/STRUCTURE.md` for Stage 4 (structure detection and content assembly)
