# Next Session: Refactor Structure Stage

## Context

We just completed testing the region correction architecture fix. The pipeline now successfully:
1. **OCR stage**: Extracts text into regions (header, body, footer, etc.) with layout detection
2. **Correction stage**: Updates ALL regions (including headers) with corrected text + `[CORRECTED:id]` markers
3. **Fix stage**: Applies targeted fixes with `[FIXED:A4-id]` markers to flagged pages
4. **Structure stage**: Currently running...

**The Problem:** We're not confident in how the structure stage currently works.

## What We Have

**Book:** Roosevelt autobiography (636 pages)
- OCR: 636 pages processed
- Correction: 631 pages corrected (5 blank pages skipped)
- Fix: 254 pages with targeted fixes applied
- Structure: In progress (was interrupted earlier)

**Current Status:**
- All pipeline stages before structure are working well
- Region correction architecture is validated and working
- Documentation updated for stages 1-3

## What Needs Review

The structure stage (`pipeline/structure/` and `pipeline/structure.py`) needs examination and likely refactoring:

### Current Approach (from docs)
1. **Load pages:** Extract body regions only (filter out headers/footers)
2. **Clean text:** Remove `[CORRECTED:id]` and `[FIXED:A4-id]` markers
3. **Detect chapters:** LLM identifies chapter boundaries
4. **Create chunks:** Split into ~5-page semantic chunks for RAG
5. **Generate output:** Markdown files for reading

### Questions to Answer
1. **Is the chapter detection approach optimal?**
   - Does it accurately find chapter boundaries?
   - Does it handle edge cases (e.g., chapters without clear titles)?

2. **Is the chunking strategy appropriate?**
   - Are ~5-page chunks the right size for RAG?
   - Should chunks respect paragraph/section boundaries?

3. **What outputs do we actually need?**
   - `full_book.md` - complete markdown
   - `chapters/*.json` - structured chapter data
   - `chunks/*.json` - RAG-ready chunks
   - Are these the right formats? Missing anything?

4. **Is header filtering working correctly?**
   - This was the main goal of the region correction fix
   - Need to verify headers are NOT in final output
   - Need to verify body text IS corrected (not raw OCR)

5. **Performance and cost?**
   - How long does structure take for 636 pages?
   - What's the cost? (Currently uses Claude Sonnet 4.5)
   - Can it be optimized?

## Files to Review

**Structure stage code:**
- `pipeline/structure.py` - Main structure detection logic
- `pipeline/structure/loader.py` - Loads pages and filters regions
- `pipeline/structure/` - Any supporting modules

**Documentation:**
- `docs/PIPELINE_ARCHITECTURE.md` - Stage 4 section needs review/update

## Success Criteria

After refactoring, we should have:
1. ✅ Clean structure stage code that's easy to understand
2. ✅ Verified header filtering (no "THEODORE ROOSEVELT—AN AUTOBIOGRAPHY" in output)
3. ✅ Correct text in output (uses corrected regions, not raw OCR)
4. ✅ Appropriate chunking for RAG use cases
5. ✅ Updated documentation matching actual implementation
6. ✅ Clear output schema (what files/formats are created)

## Key Insights from This Session

### Region Correction Architecture
The fix we implemented ensures corrections are applied to individual regions:
- Correction stage updates region text with markers
- Regions marked `corrected: true` or `fixed: true`
- Structure stage can now filter by region type while using corrected text
- This solves the previous dilemma: headers excluded BUT text is corrected

### Hardcoded Values Found and Fixed
Found `447` hardcoded in `pipeline/correct.py:732,734` as fallback for page count. This caused pages 448-636 to be skipped initially. Fixed to:
1. Count actual OCR files: `len(list(ocr_dir.glob("page_*.json")))`
2. Fall back to metadata: `metadata.get('total_pages_processed')`
3. Raise error if neither works

**Check for other hardcoded values** in structure stage and elsewhere!

### Documentation Cleanup
Removed "What changed:" sections from `PIPELINE_ARCHITECTURE.md` - git tracks changes, docs don't need to.

## Testing Data Available

We have a complete Roosevelt run ready for testing:
- `/Users/johnzampolin/Documents/book_scans/roosevelt-autobiography/`
- `ocr/page_*.json` - 636 pages with regions
- `corrected/page_*.json` - 631 pages with corrected regions
- Can verify structure output against this data

## Session Goals

1. **Review current structure implementation** - understand what it does
2. **Identify pain points** - what's unclear, inefficient, or incorrect
3. **Propose refactoring** - clearer architecture, better outputs
4. **Implement changes** - update code to match new design
5. **Test with Roosevelt** - verify headers filtered, text corrected
6. **Update docs** - ensure PIPELINE_ARCHITECTURE.md accurate for stage 4

## Open Questions

- Should we support multiple output formats (JSON, markdown, plain text)?
- Do we need chapter summaries or just chapter boundaries?
- Should chunks include metadata (page numbers, chapter context)?
- How do we handle books without clear chapter structure?
- What's the right granularity for RAG chunks?

---

**Next steps:** Start by examining the current structure stage implementation, then decide on refactoring approach.
