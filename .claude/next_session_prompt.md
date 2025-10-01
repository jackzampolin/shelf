# Next Session: Issue #30 Clean Slate Workflow Testing

## Context

We're implementing **Issue #30**: Clean slate reprocessing of all books with the optimized pipeline. This is our first end-to-end test of all the recent improvements:
- ✅ XML-structured prompts (Issue #35) - just merged
- ✅ Structure refactor (Issue #28)
- ✅ Cost tracking (Issue #29)
- ✅ Checkpoint system (Issue #33)
- ✅ Parallelization (Issue #34)
- ✅ Atomic library updates (Issue #36)

## What We've Done So Far

### 1. Fresh Start Setup ✅
- Moved `~/Documents/book_scans` → `~/Documents/book_scans_deprecated`
- Old data preserved but pipeline will start completely fresh

### 2. Documentation Cleanup ✅
- **Deleted** 5 completed planning/audit docs:
  - PIPELINE_REFACTOR_PLAN.md
  - LIBRARY_CONSISTENCY.md
  - CHECKPOINT_SYSTEM.md
  - PROMPT_AUDIT_REPORT.md
  - ATOMIC_LIBRARY_UPDATES.md
  - structure_schema.md (inaccurate)

- **Kept** only:
  - MCP_SETUP.md (user-facing)

- **Rewrote README.md**:
  - Simple workflow guide
  - Quick start → ar --help
  - Happy path documented
  - No outdated examples

### 3. Schema Documentation Audit ✅

**Critical Finding**: The old `structure_schema.md` described an aspirational v2.0 that **doesn't exist**. We deleted it. Here's what we learned:

#### What the Code Actually Does (Simple Reality)

**Directory Structure:**
```
~/Documents/book_scans/<scan-id>/structured/
├── reading/
│   ├── full_book.txt       # Clean TTS-optimized text
│   ├── metadata.json       # Chapter markers
│   └── page_mapping.json   # Scan → book page mapping
├── data/
│   ├── document_map.json   # Complete structure overview
│   ├── page_mapping.json   # Scan → book page numbers
│   ├── body/
│   │   ├── chapter_01.json  # Flat chapter structure
│   │   └── chapter_02.json
│   └── back_matter/
│       ├── notes.json       # Footnotes (if found)
│       └── bibliography.json # Bibliography (if found)
└── archive/
    └── full_book.md         # Complete markdown
```

**Key Implementation Details:**

1. **Chapters are FLAT** - No sub-chapter sections, no hierarchical structure
2. **"Paragraphs" are PAGES** - Each "paragraph" in chapter JSON is actually one full page of text
3. **No semantic paragraph detection** - Just page-level chunks
4. **Front matter directory exists but is EMPTY** - No front_matter/*.json files generated
5. **Chapter JSON structure** (actual):
   ```json
   {
     "chapter_number": 1,
     "title": "Chapter Title",
     "start_page": 15,
     "end_page": 42,
     "summary": "2-3 sentence summary",
     "paragraphs": [
       {
         "id": "ch01_p001",          // NO section number
         "text": "Full page text...", // Entire page, not semantic paragraph
         "scan_pages": [15],
         "type": "body"
         // NO: book_page, has_footnote, footnote_refs
       }
     ]
   }
   ```

6. **Notes structure** (actual):
   ```json
   {
     "note_id": 1,
     "chapter": 3,
     "text": "Full note text",
     "source_page": 250
     // NO: cited_in_paragraphs, book_page_location, bibliography_refs
   }
   ```

7. **Bibliography structure** (actual):
   ```json
   {
     "id": 1,
     "author": "Author Name",
     "title": "Book Title",
     "publisher": "Publisher",
     "year": 2020,
     "pages": 350,
     "type": "book"
     // NO: cited_on_book_pages, citation_count
   }
   ```

#### What Doesn't Exist (Documented but Not Implemented)

- ❌ Front matter JSON files (front_matter/*.json)
- ❌ Section-level structure within chapters
- ❌ Semantic paragraph detection
- ❌ Citation tracking (which paragraphs cite which notes/bibliography)
- ❌ Book page numbers in paragraphs
- ❌ Footnote reference linking
- ❌ Appendix support

## Step-by-Step Workflow Approach

We're taking a **deliberate, stop-and-check** approach:

1. ✅ Move old data to deprecated
2. ✅ Clean up documentation
3. ✅ Audit schema (learned what's real vs aspirational)
4. **Next**: Check available PDFs in ~/Documents/Scans
5. **Next**: Ingest books with `ar library ingest`
6. **Next**: Run full pipeline on SMALLEST book first (test)
7. **Next**: Verify output quality and schema
8. **Next**: Document actual schema based on real output
9. **Next**: Process remaining books
10. **Next**: Update Issue #30 with results

## Your Next Tasks

### Immediate: Check Available Books

```bash
ls -lh ~/Documents/Scans/
```

Show what PDFs we have and identify the smallest one for testing.

### Then: Create Accurate Schema Documentation

Based on the audit findings above, create `docs/OUTPUT_SCHEMA.md` that:

1. **Clearly states what's real** - No aspirational features
2. **Documents actual JSON structures** - Exact field names, types
3. **Explains key concepts**:
   - "Paragraphs" are actually full pages
   - Flat chapter structure (no sections)
   - Limited metadata extraction
4. **Shows real examples** from actual pipeline output
5. **Lists current limitations** explicitly

### Then: Run Fresh Workflow Test

1. Ingest smallest book: `ar library ingest ~/Documents/Scans/<smallest-book>.pdf`
2. Run pipeline: `ar pipeline <scan-id>`
3. Examine actual output files
4. Verify schema doc matches reality
5. Document any issues found

## Important Notes

- User wants **step-by-step with check-ins** - Don't run ahead
- We're in "hacking mode" - Document as we go, test thoroughly
- Focus on **what works**, not what should work
- Every step should verify against actual behavior

## Questions to Answer

1. What PDFs are available in ~/Documents/Scans?
2. Which is smallest (fastest to test)?
3. Does ingestion work correctly with fresh library?
4. Does pipeline produce expected output structure?
5. Are there any bugs or issues in the fresh workflow?

---

**Start here:** Check ~/Documents/Scans and propose which book to test first.
