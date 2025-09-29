# Book Text Merging System

This document describes the final stage of book digitization: merging LLM-corrected pages into clean, database-ready text with dual structures.

## Overview

After OCR extraction and LLM correction (3-agent pipeline), we need to convert the corrected pages with inline markers into clean final text. The merge system creates two complementary structures:

1. **Page Structure**: Individual pages with metadata for physical book referencing
2. **Logical Structure**: Continuous reading text organized by chapters

## Why Dual Structures?

Researchers need both:
- **Citations**: Reference physical page numbers when quoting sources
- **Reading**: Follow narrative flow across chapter boundaries
- **Search**: Find content semantically ("Stalin in Chapter 2") but return physical pages

The database can index both views simultaneously, enabling rich queries while maintaining citation accuracy.

## Input Files

The merge process expects:
```
book_scans/<book-slug>/
├── llm_agent2_corrected/         # Pages with [CORRECTED:id] markers
│   ├── page_0001.txt
│   ├── page_0002.txt
│   └── ...
├── metadata.json                  # Book metadata (total pages, etc.)
```

## Output Structure

Creates two parallel structures:

```
book_scans/<book-slug>/final_text/
├── pages/                         # Page structure
│   ├── page_0001.txt             # Clean individual pages
│   ├── page_0002.txt
│   ├── ...
│   └── pages_metadata.json       # Page metadata for DB ingestion
├── logical/                       # Logical structure
│   ├── full_text.txt             # Complete continuous text
│   ├── chapters.json             # Chapter metadata
│   ├── chapter_01.txt            # Individual chapter files
│   ├── chapter_02.txt
│   └── ...
└── merge_summary.json            # Processing statistics
```

## Cleaning Operations

Each page undergoes several cleaning steps:

### 1. Remove Correction Markers
Strips inline `[CORRECTED:id]` markers from Agent 2:
```
JULY[CORRECTED:1] 6: Truman leaves...
→
JULY 6: Truman leaves...
```

### 2. Remove Metadata Headers
Removes comment lines from top of files:
```
# Page 15
# Corrected by Agent 2
# Original errors: 6

xvi / Timeline
→
xvi / Timeline
```

### 3. Remove Headers/Footers
Detects and removes common header/footer patterns:
- Page numbers (just digits)
- Section headers ("xvi / Timeline")
- Roman numerals with slashes

### 4. Normalize Whitespace
- Collapses 3+ consecutive newlines to max 2
- Preserves paragraph structure
- Trims leading/trailing whitespace

## Page Structure

Individual page files with associated metadata:

**page_0015.txt**:
```
JULY 6: Truman leaves the White House by car at night...
```

**pages_metadata.json**:
```json
[
  {
    "page_number": 15,
    "physical_page": 15,
    "text": "...",
    "char_count": 2134,
    "word_count": 324,
    "has_content": true
  }
]
```

This structure enables:
- Direct physical page lookups for citations
- Page-level search and analysis
- Tracking empty/front-matter pages
- Word/character counts per page

## Logical Structure

Continuous text with chapter detection:

**full_text.txt**:
- All pages merged into continuous reading text
- Hyphenated words across page breaks rejoined
- Paragraph structure maintained
- Ready for semantic analysis

**chapters.json**:
```json
[
  {
    "chapter_number": 1,
    "title": "INTRODUCTION",
    "start_page": 8,
    "end_page": 15,
    "pages": [8, 9, 10, 11, 12, 13, 14, 15]
  }
]
```

**chapter_01.txt, chapter_02.txt, etc.**:
- Individual chapter files for analysis
- Include chapter title and page range headers
- Continuous text within chapter boundaries

## Chapter Detection

Automatically detects chapter breaks by recognizing patterns:
- `CHAPTER <number>` or `CHAPTER <roman>`
- `PROLOGUE`, `EPILOGUE`
- `INTRODUCTION`, `PREFACE`
- `PART <number>` or `PART <roman>`

Detection examines first 5 lines of each page for chapter markers.

## Hyphen Handling

Joins hyphenated words split across page boundaries:

**Page 12 ends with:**
```
...the most impor-
```

**Page 13 starts with:**
```
tant decision...
```

**Merged result:**
```
...the most important decision...
```

## Usage

```bash
# Merge all corrected pages
python book_llm_merge.py <book-slug>

# Example
python book_llm_merge.py The-Accidental-President
```

The script will:
1. Load corrected pages from `llm_agent2_corrected/`
2. Clean each page (remove markers, headers, footers)
3. Detect chapter structure
4. Generate both page and logical structures
5. Save output to `final_text/` directory
6. Print summary statistics

## Output Example

```
============================================================
✅ MERGE COMPLETE
============================================================

📊 Summary:
   Total pages: 447
   Pages with content: 441
   Empty pages: 6
   Total words: 142,358
   Total characters: 852,147
   Chapters detected: 12
   Avg words/page: 318

📁 Output structure:
   Logical: .../final_text/logical
   Pages:   .../final_text/pages
   Summary: .../final_text/merge_summary.json
```

## Database Ingestion

The dual structures enable flexible database schema:

**Pages Table**:
```sql
CREATE TABLE pages (
    page_id INT PRIMARY KEY,
    book_id INT,
    page_number INT,
    physical_page INT,
    text TEXT,
    char_count INT,
    word_count INT,
    has_content BOOLEAN
);
```

**Chapters Table**:
```sql
CREATE TABLE chapters (
    chapter_id INT PRIMARY KEY,
    book_id INT,
    chapter_number INT,
    title TEXT,
    start_page INT,
    end_page INT,
    text TEXT
);
```

Queries can then:
- Search semantically across continuous text
- Return physical page numbers for citations
- Analyze at page, chapter, or book granularity
- Maintain audit trail to original scans

## Known Limitations

1. **Chapter Detection**: Pattern-based detection may miss unconventional chapter styles
2. **Header/Footer Detection**: Heuristic-based, may need refinement for certain books
3. **Hyphen Handling**: Simple word rejoining, may need linguistic validation
4. **Empty Pages**: Completely blank pages have no content but maintain page numbers

## Future Enhancements

Potential improvements for Issue #27 (database ingestion):

1. **Advanced Chapter Detection**: Train ML model on book TOCs
2. **Section Detection**: Detect subsections within chapters
3. **Footnote Handling**: Parse and link footnotes to main text
4. **Index Extraction**: Parse back-of-book indices
5. **Cross-Reference Resolution**: Link page references within text
6. **Image Placement Tracking**: Note where images/figures appear
7. **Quote Boundary Detection**: Identify direct quotes for citation

## Testing

Verify merge quality by:

1. **Spot Check Pages**: Compare cleaned pages to Agent 2 output
   ```bash
   diff <(cat pages/page_0015.txt) \
        <(cat llm_agent2_corrected/page_0015.txt | sed 's/\[CORRECTED:[0-9]*\]//g')
   ```

2. **Chapter Boundaries**: Verify detected chapters match book TOC

3. **Word Count Validation**: Compare against expected book length

4. **Hyphen Rejoining**: Search for common patterns like "impor- tant" (should be none)

5. **Citation Test**: Pick random quotes, verify page numbers match physical book

## Integration with Pipeline

This is stage 4 of the complete pipeline:

1. **Scanning** (`scan_intake.py`): Physical book → PDFs
2. **OCR** (`book_ocr.py`): PDFs → Raw text
3. **LLM Correction** (`book_llm_process.py`): Raw text → Corrected text with markers
4. **Merging** (`book_llm_merge.py`): Corrected text → Clean dual structures ← **YOU ARE HERE**
5. **Database Ingestion** (Issue #27): Clean structures → Searchable database

## Related Documentation

- [SCAN_WORKFLOW.md](SCAN_WORKFLOW.md) - Book scanning process
- [BOOK_OCR.md](BOOK_OCR.md) - OCR extraction system
- [LLM_CLEANUP_PLAN.md](LLM_CLEANUP_PLAN.md) - 3-agent correction pipeline