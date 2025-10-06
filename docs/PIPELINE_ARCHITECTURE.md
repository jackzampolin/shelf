# Pipeline Architecture

## Overview

The Scanshelf pipeline transforms scanned book PDFs into structured, corrected text through four main stages. Each stage builds on the previous one, with a consistent data model throughout.

## Core Principle: Region-Based Corrections

**Key Insight:** Corrections and fixes are applied to individual OCR regions, not to flat text. This allows us to:
1. Filter out headers/footers by region type
2. Preserve OCR structure (reading order, region types)
3. Apply corrections incrementally without losing context
4. Extract clean body text for the structure stage

## Data Model

### Page JSON Structure

```json
{
  "page_number": 100,
  "regions": [
    {
      "type": "header|body|caption|footer|page_number",
      "text": "The actual text with corrections applied",
      "confidence": 0.95,
      "reading_order": 1,
      "corrected": true,    // Added by correction stage
      "fixed": true         // Added by fix stage (if needed)
    }
  ],
  "llm_processing": {
    "error_catalog": { /* Agent 1 output */ },
    "corrected_text": "Full page text with [CORRECTED:id] markers",
    "verification": { /* Agent 3 output */ },
    "agent4_fixes": {
      "fixed_text": "Full page text with [FIXED:A4-id] markers",
      "missed_corrections": [ /* What Agent 4 fixed */ ]
    }
  }
}
```

## Pipeline Stages

### Stage 1: OCR

**Input:** PDF pages
**Output:** `ocr/page_XXXX.json`

**What it does:**
- Extracts text using Tesseract OCR
- Identifies regions (header, body, footer, etc.)
- Assigns reading order to regions
- Creates initial page JSON with raw OCR text in regions

**Region text at this stage:** Raw OCR output with errors

### Stage 2: Correction (3-Agent Pipeline)

**Input:** `ocr/page_XXXX.json`
**Output:** `corrected/page_XXXX.json`

**What it does:**

#### Agent 1: Error Detection
- Analyzes page text for OCR errors
- Returns structured error catalog with `error_id`, `original_text`, `error_type`
- Does NOT provide corrected text (just identifies problems)

#### Agent 2: Apply Corrections
- Takes error catalog from Agent 1
- Returns corrected full text with `[CORRECTED:id]` markers
- Example: `"I ardently[CORRECTED:1] championed it"`

#### Agent 3: Verification
- Checks if corrections were applied correctly
- Returns confidence score and flags for human review
- Lists missed or incorrectly applied corrections

#### Region Update Step (NEW as of 2025-10-06)
After Agent 2 completes:
1. Parse `[CORRECTED:id]` markers from Agent 2's output
2. Look up original text for each error_id in Agent 1's catalog
3. Extract the corrected word (appears before the marker)
4. Find which region contains the original text
5. Update that region's text with correction + marker
6. Mark region as `corrected: true`

**Code location:** `pipeline/correct.py:552` - `apply_corrections_to_regions()`

**Region text after this stage:** Corrected text with `[CORRECTED:id]` markers

### Stage 3: Fix (Agent 4)

**Input:** Pages flagged by Agent 3 in `needs_review/`
**Output:** Updated `corrected/page_XXXX.json`

**What it does:**
- Reads Agent 3's structured feedback (missed/incorrect corrections)
- Makes ONLY the specific fixes Agent 3 identified
- Returns fixed text with `[FIXED:A4-id]` markers
- Applies fixes to regions (same as correction stage)
- Marks regions as `fixed: true`

**Code location:** `pipeline/fix.py:212` - `apply_fixes_to_regions()`

**Region text after this stage:** Corrected + fixed text with both marker types

### Stage 4: Structure

**Input:** `corrected/page_XXXX.json`
**Output:** `structured/chapters/`, `structured/chunks/`, `structured/full_book.md`

**What it does:**

#### Phase 0: Load Pages (Region Filtering)
- Extracts body regions only (type: body, caption, footnote)
- **Excludes** headers, footers, page numbers
- Removes `[CORRECTED:id]` and `[FIXED:A4-id]` markers
- Returns clean corrected text

**Code location:** `pipeline/structure/loader.py:37` - `extract_body_text()`

**Critical:** This is where header filtering happens. Because regions have corrected text, we can safely filter by type without losing corrections.

#### Phase 1: Chapter Detection
- Uses LLM to detect chapter boundaries
- Creates chapter JSON files

#### Phase 2: Chunk Creation
- Splits text into ~5-page chunks
- Adds metadata and summaries
- Creates chunk JSON files

#### Phase 3: Output Generation
- Generates `full_book.md` (complete reading text)
- Generates per-chapter markdown files

**Text at this stage:** Clean corrected body text, no headers, no markers

## Data Flow Diagram

```
PDF
 ↓
[OCR Stage]
 ↓
regions: [raw OCR text]
 ↓
[Correction Stage]
 ├─ Agent 1: Detect errors → error_catalog
 ├─ Agent 2: Apply corrections → corrected_text with [CORRECTED:id]
 ├─ Agent 3: Verify → verification feedback
 └─ apply_corrections_to_regions() → regions: [corrected text + markers]
 ↓
corrected/page_XXXX.json
 ├─ regions: [corrected text]
 └─ llm_processing.corrected_text: [full text for debugging]
 ↓
[Fix Stage] (if flagged)
 ├─ Agent 4: Apply fixes → fixed_text with [FIXED:A4-id]
 └─ apply_fixes_to_regions() → regions: [corrected + fixed text]
 ↓
[Structure Stage]
 ├─ extract_body_text() → Filter regions by type (body only)
 ├─ clean_text() → Remove markers
 └─ detect_chapters() → Create structure
 ↓
structured/chapters/*.json
structured/chunks/*.json
structured/full_book.md
```

## Why This Architecture?

### Problem it Solves

**Old approach (before 2025-10-06):**
- Correction stage created `corrected_text` but didn't update regions
- Structure stage had to choose:
  - Use regions → Get OCR errors (not corrected)
  - Use corrected_text → Get headers (not filtered)
- Result: Headers leaked into final output + OCR errors remained

**New approach (current):**
- Correction stage updates region text with corrections
- Fix stage updates region text with fixes
- Structure stage extracts body regions (corrected + no headers)
- Result: Clean text without headers or OCR errors

### Benefits

1. **Header filtering works:** Can filter by region type while using corrected text
2. **Incremental corrections:** Each stage adds to regions without losing prior work
3. **Debugging friendly:** Full text still saved in `llm_processing` for comparison
4. **Future-proof:** Region-based data enables features like per-paragraph annotations

## Implementation Checklist

When adding a new correction/fix stage:

- [ ] Parse output for markers (`[CORRECTED:id]`, `[FIXED:A4-id]`, etc.)
- [ ] Create mapping of error_id → {original, corrected}
- [ ] Iterate through regions
- [ ] Apply changes to regions that contain the original text
- [ ] Mark regions as updated (`corrected: true`, `fixed: true`, etc.)
- [ ] Save updated page JSON

See `pipeline/correct.py:552` or `pipeline/fix.py:212` for reference implementations.

## Common Mistakes to Avoid

1. ❌ **Don't fall back to full_text in structure stage**
   Full text includes headers. Always use regions.

2. ❌ **Don't create new correction text without updating regions**
   Structure stage won't see your corrections if you only update `llm_processing`.

3. ❌ **Don't skip the marker parsing step**
   Markers are how we know what changed. Parse them to update regions.

4. ❌ **Don't overwrite regions without preserving corrections**
   If you regenerate regions, you lose prior corrections. Always update in place.

## Testing Region Updates

To verify a stage is updating regions correctly:

```bash
# Run stage on test page
uv run python ar.py correct book-id --start 100 --end 100

# Check regions were marked as corrected
python3 -c "import json; d=json.load(open('path/to/page_0100.json')); \
  corrected=[r for r in d['regions'] if r.get('corrected')]; \
  print(f'Corrected regions: {len(corrected)}')"

# Verify markers in region text
python3 -c "import json; d=json.load(open('path/to/page_0100.json')); \
  body=next(r for r in d['regions'] if r['type']=='body'); \
  print('Has markers:', '[CORRECTED:' in body['text'])"

# Test structure loader extracts correctly
python3 -c "from pipeline.structure.loader import PageLoader; \
  loader=PageLoader('path/to/book'); \
  # ... test extraction"
```

## Version History

- **2025-10-06:** Implemented region correction architecture (Option A from NEXT_SESSION_PROMPT.md)
  - `pipeline/correct.py:552` - Added `apply_corrections_to_regions()`
  - `pipeline/fix.py:212` - Added `apply_fixes_to_regions()`
  - `pipeline/structure/loader.py:37` - Removed fallback to full_text
  - Result: Headers excluded, corrections preserved

---

**For questions or issues, see:**
- `NEXT_SESSION_PROMPT.md` - Original problem analysis and solution
- `CLAUDE.md` - General workflow and conventions
