# Label Stage

## Purpose

Extracts printed page numbers and classifies content blocks using vision-based analysis. Enables downstream structure extraction.

**Three-part approach:**
1. **Page number extraction** - What's printed on page (not sequential)
2. **Page region classification** - Recto/verso, front matter, main content, etc.
3. **Block classification** - BODY, HEADER, FOOTER, CHAPTER_HEADING, etc.

**See:** `pipeline/label/__init__.py:20-180`

## Processing Strategy

**Parallelization:** ThreadPoolExecutor + LLMBatchClient (same as Correction)

**Why vision?** Page numbers are *visual* - position matters, not just OCR text.

**Uses original OCR, not corrected:** Classification independent of text corrections, enables parallel processing.

**Per-page schema:** Constrains LLM to classify existing blocks only (no invention).

**See:** `pipeline/label/__init__.py:90-160` for batch processing

## Why Classification Matters

**Downstream capabilities:**
- Skip headers/footers in extraction
- Build table of contents from chapter headings
- Separate footnotes from body text
- Detect image/table regions
- Understand book structure (roman → arabic numbering = front matter → main content)

**Primary signal:** Indentation and position, NOT content analysis.

## Schemas

**Input:** OCRPageOutput (original, not corrected)

**LabelPageOutput** (`schemas.py:20-55`):
- Classified blocks (38 types: BODY, HEADER, FOOTER, CHAPTER_HEADING, FOOTNOTE, etc.)
- Printed page number + numbering style (arabic/roman)
- Page region (FRONT_MATTER, MAIN_CONTENT, BACK_MATTER, RECTO, VERSO)
- Design: Semantic layer on top of OCR structure

**LabelPageMetrics** (`schemas.py:60-75`):
- `total_blocks_classified`, `avg_classification_confidence`
- `page_number_extracted` (boolean), `page_region`

**LabelPageReport** (`schemas.py:80-90`):
- Quality focus: classification confidence and page number extraction
- Red flags: low confidence or missing page numbers

## Block Type Taxonomy (38 types)

**Main content:** BODY, CHAPTER_HEADING, SECTION_HEADING, SUBSECTION_HEADING, BLOCK_QUOTE, POETRY, LIST_ITEM

**References:** FOOTNOTE, ENDNOTE, BIBLIOGRAPHY_ENTRY, CITATION

**Structure:** HEADER, FOOTER, PAGE_NUMBER, RUNNING_HEADER, CHAPTER_TITLE

**Front/back matter:** TITLE_PAGE, COPYRIGHT, DEDICATION, PREFACE, TOC_ENTRY, INDEX_ENTRY, APPENDIX_HEADING

**Special:** IMAGE_CAPTION, TABLE_CAPTION, FIGURE_LABEL, EQUATION, CODE_BLOCK

**Metadata:** PUBLISHER_INFO, ISBN, EDITION_INFO

**See:** `pipeline/label/schemas.py:10-15` for full taxonomy

## Quality Interpretation

**avg_classification_confidence:**
- `>0.90` - High confidence (clear structure)
- `0.80-0.90` - Normal range
- `<0.80` - Ambiguous pages (review)

**page_number_extracted:**
- `false` on first pages, chapter starts, blank pages (normal)
- `false` on body pages (concerning - OCR quality issue?)

**Page region patterns:**
- FRONT_MATTER → MAIN_CONTENT at roman → arabic transition
- Expect RECTO/VERSO alternation

## Common Patterns

**Pages without printed numbers:**
- Chapter starts (often blank verso or title only)
- Front matter (title pages, copyright)
- Back matter (indices, blank ends)

**Indentation as primary signal:**
- Indented blocks → BLOCK_QUOTE or POETRY
- Hanging indent → LIST_ITEM or BIBLIOGRAPHY_ENTRY
- Position > content for classification

**Header/footer detection:**
- Relies on bbox position (top/bottom 10% of page)
- Consistent across consecutive pages

## Integration

**Uses:** OCR spatial data (bboxes, structure)

**Produces:** Semantic layer (block types, page numbers)

**Merge stage** applies classifications to OCR+Correction combined output

**Structure stage** (future) uses classifications to build document hierarchy

## Cost

Similar to Correction: ~$0.002-0.006 per page. Vision required for position analysis.

## Testing

**Unit tests:** `tests/pipeline/test_label.py`

**Manual validation:**
```bash
# Check page numbers extracted
jq '.printed_page_number' labels/page_*.json | grep -v null | wc -l

# Count block types
jq -r '.blocks[].block_type' labels/page_0050.json | sort | uniq -c
```
