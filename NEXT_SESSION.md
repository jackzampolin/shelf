# Next Session: Test Region Correction Architecture

## Context

We just implemented the region correction architecture fix. The pipeline now:
1. **Correction stage** updates regions with corrected text + `[CORRECTED:id]` markers
2. **Fix stage** updates regions with fixes + `[FIXED:A4-id]` markers
3. **Structure stage** extracts body regions only (no headers)

**Goal:** Run Roosevelt through the full pipeline manually to verify the fix works.

## What We Fixed

**Before:** Headers leaked into final output because structure stage had to choose between:
- Regions (had OCR errors, not corrected)
- Full text (had corrections, but included headers)

**After:** Regions have corrections applied, so structure stage can filter headers while using corrected text.

## Current State

- Library is empty (Roosevelt scan deleted)
- Repository clean, all changes pushed to main
- 4 commits made:
  1. `e10406e` - Implemented region correction in correction stage
  2. `45b3c68` - Extended to fix stage, added comprehensive docs
  3. `dfae1c8` - Refactored docs with progressive transformations
  4. `6fd5c2d` - Simplified docs per feedback

## Step-by-Step Testing Plan

### 1. Discover & Ingest Book

```bash
# Find available PDFs
uv run python ar.py library discover ~/Documents/Scans

# Ingest Roosevelt (if available, otherwise use another book)
uv run python ar.py library ingest <path-to-roosevelt-pdfs>

# Verify ingestion
uv run python ar.py library list
uv run python ar.py library show <scan-id>
```

**Expected:** Scan ID assigned (e.g., "wonderful-dirac"), status = "new"

### 2. Run OCR Stage

```bash
# Run OCR
uv run python ar.py ocr <scan-id>

# Check results
ls -la ~/Documents/book_scans/<scan-id>/
# Should see: ocr/, images/, source/
```

**Expected:**
- `ocr/page_*.json` files created
- Each has regions with raw OCR text (with errors)
- Status updates to "ocr_complete"

**Test one page:**
```bash
python3 -c "import json; \
  d=json.load(open('/Users/johnzampolin/Documents/book_scans/<scan-id>/ocr/page_0100.json')); \
  body=next(r for r in d['regions'] if r['type']=='body'); \
  print('Body region text:', body['text'][:200]); \
  print('Has corrected flag:', body.get('corrected', False))"
```

Should show: Raw text with errors, `corrected=False`

### 3. Run Correction Stage

```bash
# Run on single page first (test)
uv run python ar.py correct <scan-id> --start 100 --end 100

# Check results
python3 -c "import json; \
  d=json.load(open('/Users/johnzampolin/Documents/book_scans/<scan-id>/corrected/page_0100.json')); \
  body=next(r for r in d['regions'] if r['type']=='body'); \
  print('Corrected:', body.get('corrected', False)); \
  print('Has markers:', '[CORRECTED:' in body['text']); \
  print('Text sample:', body['text'][:200])"
```

**Expected:**
- `corrected=True`
- `[CORRECTED:id]` markers in text
- Text has corrections applied

**If good, run full correction:**
```bash
uv run python ar.py correct <scan-id>
# Takes ~10-15 minutes for 636 pages
# Cost: ~$0.76 for Roosevelt with gpt-4o-mini
```

### 4. Run Fix Stage (Optional)

```bash
# Check how many pages need fixing
ls ~/Documents/book_scans/<scan-id>/needs_review/ | wc -l

# Run fix on flagged pages
uv run python ar.py fix <scan-id>
# Takes ~5 minutes
# Cost: ~$0.30-0.50
```

**Expected:** Low-confidence pages get targeted fixes, regions updated with `[FIXED:A4-id]` markers

### 5. Run Structure Stage

```bash
# Run structure detection and chunking
uv run python ar.py structure <scan-id>
# Takes ~2 minutes
# Cost: ~$0.50
```

**Expected:**
- `structured/chapters/*.json` created
- `structured/chunks/*.json` created
- `structured/full_book.md` created

### 6. Verify Headers Excluded

```bash
# Count headers in final output (should be 0 or near-0)
grep -c "THEODORE ROOSEVELT\|AUTOBIOGRAPHY" \
  ~/Documents/book_scans/<scan-id>/structured/full_book.md

# Compare with chapter text
head -100 ~/Documents/book_scans/<scan-id>/structured/full_book.md
```

**Expected:**
- **Before fix:** ~40 headers appeared in text
- **After fix:** 0 headers (or very few false positives)

**Success criteria:**
- Headers filtered out
- Body text is corrected (no OCR errors like "ardontly")
- Text flows naturally

### 7. Verify Data Quality

```bash
# Check a sample chapter
cat ~/Documents/book_scans/<scan-id>/structured/chapters/chapter_01.md | head -50

# Verify no markers in final output
grep -E '\[CORRECTED:\d+\]|\[FIXED:A4-\d+\]' \
  ~/Documents/book_scans/<scan-id>/structured/full_book.md

# Should return nothing - markers should be stripped
```

## Troubleshooting

**If headers still appear:**
1. Check page_0100.json - are regions marked `corrected: true`?
2. Check if structure loader is using regions: `pipeline/structure/loader.py:37`
3. Verify no fallback to full_text is happening

**If no corrections applied:**
1. Check correction stage output - look for markers in corrected text
2. Verify `apply_corrections_to_regions()` is being called
3. Check logs in `~/Documents/book_scans/<scan-id>/logs/`

**If markers in final output:**
1. Structure loader should call `clean_text()` which strips markers
2. Check `pipeline/structure/loader.py:21`

## Key Files to Reference

- **`docs/PIPELINE_ARCHITECTURE.md`** - How each stage works
- **`pipeline/correct.py:552`** - Region update logic for correction
- **`pipeline/fix.py:212`** - Region update logic for fix
- **`pipeline/structure/loader.py:37`** - Body text extraction

## Success Metrics

- ✅ Regions updated with corrections (check page_0100.json)
- ✅ Headers filtered from final output (count should be 0)
- ✅ No markers in final markdown
- ✅ Text quality high (no OCR errors in body)

## Cost Estimate

For Roosevelt (636 pages):
- OCR: Free (Tesseract)
- Correction: ~$0.76 (gpt-4o-mini)
- Fix: ~$0.40 (Claude 3.5 Sonnet, only flagged pages)
- Structure: ~$0.50 (Claude Sonnet 4.5)
- **Total: ~$1.66**

Much cheaper than the $12 we initially estimated!

## After Testing

If everything works:
1. Document the results
2. Consider running fix stage to clean up remaining issues
3. Test MCP server to query the book
4. Mark this architectural change as validated

---

**Remember:** Run each stage manually and verify output at each step. This lets you catch issues early and understand the data flow.
