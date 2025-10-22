# Merge Stage

## Purpose

Deterministic three-way merge of OCR + Correction + Label outputs. Produces unified page representation with corrected text, spatial data, and semantic classifications.

**Zero cost** - No LLM calls, pure logic.

**See:** `pipeline/merged/__init__.py:20-150`

## Processing Strategy

**Parallelization:** ThreadPoolExecutor with 8 workers (I/O-bound file reading)

**Deterministic algorithm:** No randomness, same inputs always produce same output.

**Performance:** ~16 pages/second (400 pages in <30 seconds)

**See:** `pipeline/merged/__init__.py:80-130` for merge logic

## Merge Logic (Five Components)

**1. Text Selection:**
```python
text = corrected_text if exists else ocr_text
```
Correction precedence - use fixes when available, fallback to OCR.

**2. Spatial Data:**
Bboxes ALWAYS from OCR (ground truth), never corrected (prevents drift).

**3. Classification:**
Block types from Label stage (BODY, HEADER, CHAPTER_HEADING, etc.).

**4. Page Numbering:**
Printed page numbers and styles (roman/arabic) from Label.

**5. Metadata:**
Full provenance: which sources contributed, models used, timestamps.

## Schemas

**Dependencies:** ["ocr", "corrected", "labels"]

**Validation:** Requires 1-1-1 correspondence (same page numbers across all three sources).

**MergedPageOutput** (`schemas.py:20-60`):
- Combined blocks with: corrected text, OCR bboxes, Label classifications
- Correction metadata per block (was_corrected, correction_confidence, correction_notes)
- Page-level metadata (printed_page_number, page_region, numbering_style)
- Paragraph continuation markers (to_next_page, from_previous_page)

**MergedPageMetrics** (`schemas.py:65-75`):
- `total_blocks_merged`, `corrections_used_count`, `correction_rate`
- `pages_with_continuation` (text flow tracking)

## Continuation Detection

**Algorithm:**

```python
continues_to_next = (
    last_paragraph is BODY and
    not ends_with_terminal_punctuation and
    not ends_with_hyphen
)

continues_from_previous = (
    first_paragraph is BODY and
    starts_with_lowercase
)
```

**Accuracy:** ~90% heuristic (intentionally simple, zero cost)

**False positives:** Abbreviations, numbers, quoted text ending paragraphs.

**Purpose:** Helps Structure stage reconstruct logical paragraphs across page breaks.

**See:** `pipeline/merged/__init__.py:110-125`

## Quality Interpretation

**correction_rate:**
- `10-30%` - Normal (indicates OCR quality)
- `<10%` - Excellent OCR or few corrections made
- `>40%` - Poor OCR or aggressive correction

**continuation_rate:**
- `5-15%` - Normal text flow
- `<5%` - Short paragraphs or poetry
- `>20%` - Dense prose or technical writing

## Integration

**Uses:** OCR (spatial + fallback text), Correction (text fixes), Label (semantics)

**Produces:** Complete page representation for Structure stage

**Structure stage** (future) will use:
- Block classifications (identify chapters, sections)
- Page numbers (understand book organization)
- Continuation markers (rebuild logical paragraphs)
- Spatial data (detect visual patterns)

## Common Issues

**1-1-1 mismatch:**
- Symptom: FileNotFoundError in before()
- Cause: Incomplete upstream stage or page filtering
- Fix: Run all three stages to completion first

**High correction_rate but low corrections_used:**
- Symptom: Many corrections available but not applied
- Cause: Merge logic bug or schema mismatch
- Fix: Check correction schema matches merge expectations

**All continuations false:**
- Normal for poetry, dialogue-heavy text, or short-form content
- Check block types (non-BODY blocks don't get continuation markers)

## Testing

**Unit tests:** `tests/pipeline/test_merged.py`

**Manual validation:**
```bash
# Check merge completeness
jq '.blocks | length' merged/page_0050.json

# Verify correction application
jq '.blocks[] | select(.was_corrected == true) | .text' merged/page_0050.json

# Check continuation markers
jq '.metadata.continues_to_next_page' merged/page_*.json | grep -c true
```

## Performance Tuning

**Worker count:**
- 4 workers: Low I/O contention, slower
- 8 workers: Balanced (default)
- 16 workers: Faster but diminishing returns

**Bottleneck:** File I/O (reading three JSON files per page), not computation.

**Optimization:** SSD storage makes biggest difference.
