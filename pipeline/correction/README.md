# Correction Stage

## Purpose

Vision-based character-level OCR error correction using multimodal LLMs. Fixes obvious pixel-level mistakes while preserving layout structure.

**Design principle:** Trust Tesseract's layout, fix its character recognition errors.

**See:** `pipeline/correction/__init__.py:20-200`

## Processing Strategy

**Parallelization:** ThreadPoolExecutor + LLMBatchClient with `Config.max_workers` (default 30)

**Why I/O-bound?** LLM API calls dominate - latency, not computation. ThreadPoolExecutor optimal.

**Per-page schema generation:** Enforces structural constraints - LLM can only correct text within existing blocks/paragraphs, can't add/remove structure (prevents hallucinations).

**Image downsampling:** 300 DPI → reduces tokens 50%, preserves readability, cuts costs in half.

**See:** `pipeline/correction/__init__.py:100-180` for batch processing

## Why Vision Models?

OCR text alone misses context:
- "rn" vs "m" ambiguity
- "cl" vs "d" confusion
- "0" vs "O" in mixed contexts

Vision models see actual pixels, verify OCR against image. Cost: ~$0.002-0.006 per page.

## Schemas

**Input:** OCRPageOutput (from OCR stage)

**CorrectionPageOutput** (`schemas.py:15-40`):
- Sparse corrections - only blocks/paragraphs with text changes
- Preserves original structure, stores corrected text + confidence + notes
- Design: Minimal output (only what changed), enables merge later

**CorrectionPageMetrics** (`schemas.py:50-75`):
- Extends LLMPageMetrics (tokens, timing, cost, model)
- Adds: `total_corrections`, `avg_confidence`, `text_similarity_ratio`, `characters_changed`

**CorrectionPageReport** (`schemas.py:80-90`):
- Quality focus: corrections and similarity only (excludes tokens/cost)
- Red flags: similarity <0.85 or corrections >40%

## Quality Interpretation

**text_similarity_ratio:**
- `0.95-1.0` - Expected (minor fixes)
- `0.90-0.95` - Normal (moderate corrections)
- `0.85-0.90` - Concerning (major rewrites)
- `<0.85` - Red flag (verify not hallucinating)

**total_corrections (percentage):**
- `1-5%` - Clean modern books
- `5-15%` - Technical/historical text
- `20-40%` - Poor OCR quality
- `>40%` - Verify with manual review

**avg_confidence:**
- `>0.95` - High confidence corrections
- `0.85-0.95` - Normal range
- `<0.85` - Uncertain fixes (review report.csv)

## Cost Optimization

**Full book (~400 pages):** 1M tokens = $1-4 depending on model

**Optimizations:**
1. Image downsampling: 10-40x size reduction
2. Rate limiting: 100 req/min default
3. Structural constraints: Prevents excessive generation
4. Batch processing: Amortizes queue time

**Cost tracking:** Every page in checkpoint, aggregated in report.

## Integration

**Uses:** OCR text + source images

**Produces:** Sparse corrections (only changed text)

**Merge stage** combines corrections with OCR (corrected text > OCR text)

**Note:** Corrections independent of labels - stages can run in parallel.

## Common Issues

**High similarity (>0.98) but many corrections:**
- OCR was already good, LLM making small fixes
- Normal for modern books

**Low similarity (<0.85):**
- Poor OCR quality OR hallucination
- Check report.csv for specific pages
- Manual review recommended

**Cost higher than expected:**
- Check image sizes (downsample more aggressively)
- Verify rate limiting not too conservative
- Consider faster/cheaper model for clean books

## Testing

**Unit tests:** `tests/pipeline/test_correction.py`

**Manual validation:**
```bash
# Compare OCR to correction
diff <(jq -r '.blocks[0].paragraphs[0].text' ocr/page_0001.json) \
     <(jq -r '.blocks[0].paragraphs[0].text' corrected/page_0001.json)
```
