# First Book Processing Plan

**Purpose:** Process first production book with manual validation at each stage to ensure quality before scaling up.

**Approach:** Run each stage separately, validate outputs, check for issues, then proceed to next stage.

**Why Manual?** Catch problems early, understand actual performance vs. estimates, build confidence in pipeline.

---

## Pre-Processing: Setup & Selection

### 1. Choose Your Book

**Criteria for first book:**
- ✅ **Medium length** (200-400 pages) - Not too long, not too short
- ✅ **Good scan quality** - Clean PDF, readable text
- ✅ **Known content** - Ideally something you're familiar with (easier to spot errors)
- ✅ **Biography or history** - Well-structured (chapters, footnotes, bibliography)
- ❌ **Avoid:** Mathematical formulas, heavy diagrams, poetry (different OCR challenges)

### 2. Pre-Flight Checklist

```bash
# Check available PDFs
ls -lh ~/Documents/Scans/

# Verify environment
source .venv/bin/activate
which python  # Should show .venv/bin/python

# Check API key
grep OPENROUTER_API_KEY .env
# Should show: OPENROUTER_API_KEY=sk-...

# Check disk space (need ~500MB per book)
df -h ~/Documents/book_scans/

# Verify library is working
ar library list
ar library stats
```

**Expected Results:**
- PDFs found in ~/Documents/Scans/
- Virtual environment activated
- API key present and valid
- At least 2GB free disk space
- Library commands run without errors

---

## Stage 0: Ingestion (5-10 minutes)

### Command

```bash
# Add book to library (this generates scan-id and extracts metadata)
ar add ~/Documents/Scans/your-book-*.pdf

# Example with multi-part PDF:
# ar add ~/Documents/Scans/accidental-president-1.pdf ~/Documents/Scans/accidental-president-2.pdf

# Example with custom ID:
# ar add ~/Documents/Scans/my-book.pdf --id my-custom-name
```

### What This Does
1. Vision LLM analyzes first 10 pages
2. Extracts title, author, year, publisher
3. Generates random scan-id (e.g., "modest-lovelace")
4. Creates directory: `~/Documents/book_scans/<scan-id>/`
5. Copies/combines PDFs to `source/` directory
6. Registers book in `library.json`
7. Creates initial `metadata.json`

### Validation Checks

```bash
# Get the scan-id from output (e.g., "modest-lovelace")
SCAN_ID="<scan-id-from-output>"

# Check directory created
ls -la ~/Documents/book_scans/$SCAN_ID/

# Check source PDFs
ls -lh ~/Documents/book_scans/$SCAN_ID/source/

# Check metadata
cat ~/Documents/book_scans/$SCAN_ID/metadata.json | python -m json.tool

# Verify in library
ar library show $SCAN_ID
```

**What to Look For:**
- ✅ Directory exists with scan-id
- ✅ Source PDFs present (combined if multi-part)
- ✅ Metadata has correct title/author
- ✅ `ar library show` displays book info
- ❌ Red flag: Wrong title/author → May need manual correction in library.json

### Cost & Time
- **Time:** 2-5 minutes (vision LLM call)
- **Cost:** ~$0.10 (10 pages analyzed)

---

## Stage 1: OCR (10-20 minutes for 400 pages)

### Command

```bash
# Run OCR stage only
ar ocr $SCAN_ID

# Monitor in another terminal
ar status $SCAN_ID --watch
```

### What This Does
1. Converts PDF pages to images
2. Runs Tesseract OCR on each page
3. Detects regions (header, body, footer, caption, page number)
4. Saves structured JSON: `ocr/page_0001.json`, `ocr/page_0002.json`, etc.
5. Creates checkpoint: `checkpoints/ocr.json`

### Validation Checks

```bash
# Check OCR output directory
ls ~/Documents/book_scans/$SCAN_ID/ocr/ | wc -l
# Should match page count

# Examine a few pages
cat ~/Documents/book_scans/$SCAN_ID/ocr/page_0001.json | python -m json.tool | head -50
cat ~/Documents/book_scans/$SCAN_ID/ocr/page_0100.json | python -m json.tool | head -50

# Check for region detection
grep -o '"type": "[^"]*"' ~/Documents/book_scans/$SCAN_ID/ocr/page_0050.json | sort | uniq -c

# Check checkpoint
cat ~/Documents/book_scans/$SCAN_ID/checkpoints/ocr.json | python -m json.tool
```

**What to Look For:**

**Good Signs:**
- ✅ Page count matches PDF page count
- ✅ JSON files have `regions` array
- ✅ Region types: header, body, footer, caption, page_number
- ✅ Text looks readable (even with OCR errors)
- ✅ Checkpoint shows `"status": "completed"`

**Red Flags:**
- ❌ Missing pages (count mismatch)
- ❌ Empty regions arrays
- ❌ Gibberish text (indicates very poor scan quality)
- ❌ All text classified as one region type

**Sample Good Output:**
```json
{
  "page_number": 50,
  "regions": [
    {
      "id": "r0",
      "type": "header",
      "text": "50 CHAPTER THREE",
      "confidence": 0.95
    },
    {
      "id": "r1",
      "type": "body",
      "text": "The events of 1912 were signifcant in reshaping...",
      "confidence": 0.89
    }
  ]
}
```

### Cost & Time
- **Time:** 10-20 minutes (400 pages, 16 parallel workers)
- **Cost:** **FREE** (Tesseract is local)

### Common Issues & Fixes

**Issue:** OCR very slow (>30 min for 400 pages)
- Check CPU usage: `top` (should see multiple tesseract processes)
- Reduce workers if system struggling: Add `--ocr-workers 8` to command

**Issue:** Some pages fail
- Check logs: `tail -f ~/Documents/book_scans/$SCAN_ID/logs/ocr.log`
- Usually okay if <5% failure rate
- Failed pages will have empty/minimal regions

---

## Stage 2: Correction (10-15 minutes for 400 pages)

### Command

```bash
# Run correction stage (3-agent pipeline)
ar correct $SCAN_ID

# Monitor progress
ar status $SCAN_ID --watch
```

### What This Does
1. Loads OCR pages
2. Runs 3-agent correction on each page (parallel, 30 workers):
   - **Agent 1:** Detect OCR errors
   - **Agent 2:** Apply corrections with `[CORRECTED:id]` markers
   - **Agent 3:** Verify quality, flag low-confidence pages
3. Updates regions with corrections
4. Saves: `corrected/page_0001.json`, etc.
5. Flags problematic pages: `needs_review/page_*.json`
6. Creates checkpoint with costs

### Validation Checks

```bash
# Check corrected output
ls ~/Documents/book_scans/$SCAN_ID/corrected/ | wc -l
# Should match page count

# Compare OCR vs Corrected for a challenging page
echo "=== OCR (Original) ==="
grep -o '"text": "[^"]*"' ~/Documents/book_scans/$SCAN_ID/ocr/page_0100.json | head -3

echo "=== Corrected ==="
grep -o '"text": "[^"]*"' ~/Documents/book_scans/$SCAN_ID/corrected/page_0100.json | head -3

# Check for correction markers
grep -o '\[CORRECTED:[0-9]*\]' ~/Documents/book_scans/$SCAN_ID/corrected/page_0100.json | wc -l
# Should see markers if errors were fixed

# Check flagged pages
ls ~/Documents/book_scans/$SCAN_ID/needs_review/ | wc -l
# Typically 5-15% of pages

# Check costs
cat ~/Documents/book_scans/$SCAN_ID/checkpoints/correction.json | python -m json.tool | grep -A5 "costs"

# View correction stats
ar status $SCAN_ID
```

**What to Look For:**

**Good Signs:**
- ✅ All pages corrected (count matches)
- ✅ `[CORRECTED:X]` markers present in text
- ✅ Obvious OCR errors fixed ("tbe" → "the", "signifcant" → "significant")
- ✅ Flagged pages: 5-20% (normal range)
- ✅ Cost: ~$8-12 for 400 pages (gpt-4o-mini)

**Red Flags:**
- ❌ >30% pages flagged → Poor scan quality or model issues
- ❌ Cost >>$15 for 400 pages → Check API rate limiting
- ❌ No correction markers → Pipeline not running properly
- ❌ Text completely different → Over-correction (rare but check)

**Sample Before/After:**
```
OCR:      "Tbe President signifcant role in tbe govermment..."
Corrected: "The[CORRECTED:1] President significant[CORRECTED:2] role in the[CORRECTED:3] government[CORRECTED:4]..."
```

### Cost & Time
- **Time:** 10-15 minutes (400 pages, 30 parallel workers, rate-limited)
- **Cost:** ~$8-12 (gpt-4o-mini @ ~$0.02-0.03/page)

### Common Issues & Fixes

**Issue:** Many pages flagged (>25%)
- Expected for difficult scans (old books, poor quality)
- Will be addressed in Stage 3 (Fix)
- Can review sample: `cat ~/Documents/book_scans/$SCAN_ID/needs_review/page_0050.json`

**Issue:** Cost much higher than expected
- Check model: Should be `gpt-4o-mini` not `gpt-4`
- Verify in checkpoint: `grep "model" ~/Documents/book_scans/$SCAN_ID/checkpoints/correction.json`

**Issue:** Processing stalls
- Check OpenRouter status: https://openrouter.ai/status
- Check rate limits: Correction uses 150 calls/minute by default
- Can reduce workers: `ar correct $SCAN_ID --correct-workers 15`

---

## Stage 3: Fix (2-5 minutes for flagged pages)

### Command

```bash
# Run fix stage (Agent 4 targeted corrections)
ar fix $SCAN_ID

# Monitor
ar status $SCAN_ID --watch
```

### What This Does
1. Loads flagged pages from `needs_review/`
2. For each flagged page:
   - Reads Agent 3's specific feedback
   - Applies surgical fixes with `[FIXED:A4-id]` markers
   - Updates `corrected/page_*.json` (overwrites)
3. Uses Claude Sonnet 4.5 (best model for precision)
4. **Now tracks actual costs!** (our fix from today)

### Validation Checks

```bash
# Check which pages were fixed
ls ~/Documents/book_scans/$SCAN_ID/needs_review/ | wc -l
# Number of pages that were flagged

# Check fix markers in a corrected page
grep -o '\[FIXED:A4-[0-9]*\]' ~/Documents/book_scans/$SCAN_ID/corrected/page_0100.json | wc -l

# Check fix costs (NEW - we just implemented this!)
cat ~/Documents/book_scans/$SCAN_ID/checkpoints/fix.json | python -m json.tool | grep -A5 "costs"

# Compare before/after on a flagged page
# (Compare correction vs fix if you saved earlier snapshot)

# Check status
ar status $SCAN_ID
```

**What to Look For:**

**Good Signs:**
- ✅ All flagged pages processed
- ✅ `[FIXED:A4-X]` markers present
- ✅ Cost: ~$0.50-2.00 for 20-50 flagged pages
- ✅ Confidence improved on previously low-confidence pages

**Red Flags:**
- ❌ Cost = $0.00 → Old version without our fix (shouldn't happen)
- ❌ No fix markers → Agent 4 might not have found issues to fix
- ❌ Fix cost >$5 for 50 pages → Unexpectedly expensive

### Cost & Time
- **Time:** 2-5 minutes (only flagged pages, ~5-15% of total)
- **Cost:** ~$0.50-2.00 (Claude Sonnet 4.5, targeted fixes only)

---

## Stage 4: Structure (5-10 minutes for 400 pages)

### Command

```bash
# Run structure extraction
ar structure $SCAN_ID

# Monitor
ar status $SCAN_ID --watch
```

### What This Does
1. **Phase 1: Sliding Window Extraction**
   - 3-page batches with 1-page overlap
   - Extract clean body text (remove headers/footers)
   - Verify quality with full-text comparison
   - Reconcile overlaps between batches
   - Saves: `structured/extraction/batch_*.json`

2. **Phase 2: Assembly & Chunking**
   - Merge batches into complete book
   - Build document map (chapters, sections)
   - Create semantic chunks for RAG (~5 pages each)
   - Generate three output formats:
     - `structured/reading/full_book.txt` (TTS-ready)
     - `structured/data/body/chapter_*.json` (RAG-ready)
     - `structured/archive/full_book.md` (human-readable)

### Validation Checks

```bash
# Check extraction batches
ls ~/Documents/book_scans/$SCAN_ID/structured/extraction/ | wc -l
# Should be ~133 batches for 400 pages (400/3 with overlap)

# Check outputs created
ls -lh ~/Documents/book_scans/$SCAN_ID/structured/reading/
ls -lh ~/Documents/book_scans/$SCAN_ID/structured/data/body/
ls -lh ~/Documents/book_scans/$SCAN_ID/structured/archive/

# Check metadata
cat ~/Documents/book_scans/$SCAN_ID/structured/metadata.json | python -m json.tool

# Spot-check content quality
head -100 ~/Documents/book_scans/$SCAN_ID/structured/archive/full_book.md

# Check chapter detection
ls ~/Documents/book_scans/$SCAN_ID/structured/data/body/*.json | wc -l
# Number of chapters detected

# Verify chunks
ls ~/Documents/book_scans/$SCAN_ID/structured/data/body/*.json | head -3 | xargs -I {} sh -c 'echo "=== {} ===" && cat {} | python -m json.tool | head -20'

# Check structure costs
cat ~/Documents/book_scans/$SCAN_ID/checkpoints/structure.json 2>/dev/null | python -m json.tool | grep -A5 "costs"
```

**What to Look For:**

**Good Signs:**
- ✅ Batch count reasonable (~page_count / 2)
- ✅ `full_book.md` is readable, no gibberish
- ✅ Running headers removed (not repeated on every page)
- ✅ Chapters detected (>0 chapter files)
- ✅ Chunks have provenance (`scan_pages`, `book_pages`)
- ✅ Cost: ~$1-3 for 400 pages
- ✅ No huge gaps in text (completeness check)

**Red Flags:**
- ❌ `full_book.md` is empty or very short
- ❌ Running headers still present ("CHAPTER 3" on every page)
- ❌ No chapters detected (0 files)
- ❌ Chunks missing `scan_pages` or `book_pages`
- ❌ Cost >$5 for 400 pages
- ❌ Text quality worse than corrected stage

**Manual Spot Checks:**
1. Open `full_book.md` - does it read naturally?
2. Check a chapter file - is text clean and structured?
3. Find a footnote in original PDF - is it preserved?
4. Check bibliography - is it present and formatted?

### Cost & Time
- **Time:** 5-10 minutes (400 pages, Phase 1 + Phase 2)
- **Cost:** ~$1-3 (GPT-4o-mini for extraction, Claude for chapter detection)

### Common Issues & Fixes

**Issue:** Running headers not removed
- Check a batch file: Does it still have "CHAPTER 3" repeated?
- This indicates extraction agent needs better prompting
- Usually fixed in newer versions

**Issue:** Missing chapters
- Check if book has clear chapter markers
- Some books use different formatting (parts, sections, etc.)
- May need manual chapter marking for non-standard formats

---

## Post-Processing: Final Validation

### Overall Quality Check

```bash
# Get complete status
ar library show $SCAN_ID

# Check all stages completed
ar status $SCAN_ID

# Review cost breakdown
ar library stats

# Validate outputs exist
find ~/Documents/book_scans/$SCAN_ID -type f -name "*.json" -o -name "*.md" -o -name "*.txt" | wc -l
# Should have hundreds of files
```

### Content Spot Checks

**1. Pick 3 random pages from PDF**
- Choose beginning (page 50)
- Choose middle (page 200)
- Choose end (page 350)

**2. For each page, verify:**
```bash
PAGE=50

# Find the text in full_book.md
grep -A10 "some unique phrase from page $PAGE" ~/Documents/book_scans/$SCAN_ID/structured/archive/full_book.md

# Check if it's in correct chapter
# (Find chapter that contains those scan pages)
```

**3. Test search functionality**
```bash
# Search for a known phrase
grep -r "specific phrase you remember" ~/Documents/book_scans/$SCAN_ID/structured/data/

# Should find it in appropriate chapter/chunk files
```

### Expected Final Costs (400-page book)

| Stage | Model | Cost | Time |
|-------|-------|------|------|
| Ingest | Vision | $0.10 | 2-5min |
| OCR | Tesseract | $0.00 | 10-20min |
| Correction | gpt-4o-mini | $8-12 | 10-15min |
| Fix | Claude Sonnet 4.5 | $0.50-2 | 2-5min |
| Structure | Hybrid | $1-3 | 5-10min |
| **Total** | | **$10-17** | **30-55min** |

**Per-page cost:** ~$0.025-0.04

---

## Decision Points: Continue or Stop

### ✅ GREEN LIGHT - Proceed to Next Book
- All stages completed successfully
- Costs within expected range ($10-17 for 400 pages)
- Quality spot checks pass
- No major errors or missing content
- Library stats show accurate totals

**Action:** Process next book with same workflow!

### 🟡 YELLOW LIGHT - Investigate First
- Costs higher than expected (>$20 for 400 pages)
- 20-30% pages flagged in correction
- Some missing content in spot checks
- Structure stage didn't detect chapters well

**Action:** Review specific issues, may need prompting adjustments

### 🔴 RED LIGHT - Don't Continue
- Pipeline failures or crashes
- Costs >>$25 for 400 pages
- >40% pages flagged
- Gibberish or corrupted output
- Missing large sections of content

**Action:** Debug specific stage, check logs, may need code fixes

---

## Troubleshooting Guide

### Pipeline Stops/Hangs

```bash
# Check for running processes
ps aux | grep python

# Check logs
tail -f ~/Documents/book_scans/$SCAN_ID/logs/*.log

# Check OpenRouter status
curl https://openrouter.ai/api/v1/auth/key \
  -H "Authorization: Bearer $OPENROUTER_API_KEY"
```

### Costs Too High

```bash
# Check which model was used
grep "model" ~/Documents/book_scans/$SCAN_ID/checkpoints/*.json

# Check per-stage costs
ar library stats

# Verify rate limiting is working
grep "rate" ~/Documents/book_scans/$SCAN_ID/logs/*.log
```

### Poor Quality Output

```bash
# Check OCR confidence scores
grep "confidence" ~/Documents/book_scans/$SCAN_ID/ocr/page_0100.json

# Check correction stats
grep "total_errors_found" ~/Documents/book_scans/$SCAN_ID/corrected/page_0100.json

# Check flagged page reasons
cat ~/Documents/book_scans/$SCAN_ID/needs_review/page_0100.json | python -m json.tool | grep "review_reason"
```

---

## Success Criteria Checklist

Before processing book #2, ensure:

- [ ] All 4 stages completed (OCR, Correction, Fix, Structure)
- [ ] `ar library show $SCAN_ID` shows complete metadata
- [ ] `ar library stats` shows accurate costs and breakdown
- [ ] Total cost in expected range ($10-17 for 400 pages)
- [ ] `structured/archive/full_book.md` is readable
- [ ] Spot checks: 3 random pages found and accurate
- [ ] No major errors in logs
- [ ] Checkpoint files exist for all stages
- [ ] You understand what each stage does
- [ ] You know how to interpret validation checks

---

## Next Steps After Success

1. **Process Book #2** - Use same workflow, compare results
2. **Try different book type** - Different genre, length, or quality
3. **Batch processing** - Once confident, use `ar process` for full automation
4. **MCP setup** - Query books from Claude Desktop (see `docs/MCP_SETUP.md`)
5. **Cost optimization** - If costs are consistent, you're good to scale

---

## Key Learnings to Document

After processing first book, note:
- Actual time per stage vs. estimates
- Actual cost per stage vs. estimates
- Any unexpected errors or issues
- Quality of different stages' outputs
- Books that worked well vs. poorly
- Any prompting improvements needed

This feedback will improve the pipeline for future books!
