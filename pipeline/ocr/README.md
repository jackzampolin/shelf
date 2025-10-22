# OCR Stage

## Purpose

Extracts text, layout, and images from page images using Tesseract OCR. First stage in pipeline - creates source of truth for all downstream processing.

**Core question answered:** "What text is on this page, where is it, and how confident are we?"

**See:** `pipeline/ocr/__init__.py:20-165`

## Processing Strategy

**Parallelization:** ProcessPoolExecutor with `cpu_count()` workers (CPU-bound Tesseract)

**Why CPU-bound?** Tesseract is local computation, not I/O. ThreadPoolExecutor would hit GIL contention.

**Tesseract hierarchy preserved:**
```
Page → Blocks → Paragraphs → Words
```

Each level includes bboxes, text, and confidence. Paragraph-level detail saves 6x multimodal costs vs word-level while preserving spatial intelligence.

**Image extraction:** OpenCV detects regions, saves to `images/page_NNNN_img_NNN.png` for downstream multimodal use.

**See:** `pipeline/ocr/__init__.py:90-140` for worker implementation

## Schemas

**OCRPageOutput** (`schemas.py:10-35`):
- Hierarchical blocks → paragraphs → words
- Bboxes at all levels (enables spatial analysis)
- Images list (extracted regions)
- Design: Preserve Tesseract structure, don't interpret yet

**OCRPageMetrics** (`schemas.py:40-50`):
- `confidence_mean` - Average across all words
- `blocks_detected` - Layout complexity indicator
- Zero cost (Tesseract is free)

**OCRPageReport** (`schemas.py:55-60`):
- Quality-focused: confidence and block count only
- Use to identify problematic pages before expensive correction

## Unique Features

### Metadata Extraction (after() hook)

Extracts book metadata from first 15 OCR pages using single LLM call:
- Title, author, year, publisher, ISBN, book type
- Stored in `metadata.json` at book level
- Used by downstream stages for context

**See:** `pipeline/ocr/__init__.py:150-165`

**Why after OCR?** Needs structured text, runs once per book (not per page).

## Quality Interpretation

**Confidence thresholds:**
- `0.95+` - Excellent (modern printed books)
- `0.85-0.95` - Good (typical quality)
- `0.70-0.85` - Concerning (historical/poor scans)
- `<0.70` - Poor (needs re-scanning)

**Block counts:**
- `1-2` - Simple pages (chapter titles)
- `3-10` - Normal text pages
- `11+` - Dense (footnotes, tables, multi-column)

**report.csv columns:** page_num, confidence_mean, blocks_detected

## Common Issues

**Tesseract fails when:**
- Handwritten text (designed for printed only)
- Extreme skew/rotation (>5 degrees)
- Very low resolution (<200 DPI)
- Unusual fonts (blackletter, decorative)

**Solutions:**
- Check source image quality first
- Verify orientation (Tesseract auto-rotate is imperfect)
- Consider manual preprocessing for problem pages

## Integration

**Correction stage** uses OCR text + images to fix errors

**Label stage** uses block structure for classification

**Merge stage** combines OCR spatial data with corrections

OCR is **read-only** for downstream - never modified after creation.

## Cost

CPU time only (Tesseract is local). Metadata extraction: ~$0.001 per book.

Worker count affects memory (50MB per worker) and I/O contention, not cost.

## Testing

**Unit tests:** `tests/pipeline/test_ocr.py`

**Manual validation:**
```bash
jq '.blocks[].paragraphs[].text' ~/Documents/book_scans/{scan-id}/ocr/page_0001.json
```
