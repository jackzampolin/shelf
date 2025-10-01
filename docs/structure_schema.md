# Structure Stage Schema v2.0

This document defines the output schema for the refactored structure stage, which implements a three-output strategy optimized for different use cases: text-to-speech, RAG/analysis, and archival.

## Overview

The structure stage takes corrected page-level text and produces three distinct outputs:

1. **Reading Output** (`structured/reading/`) - TTS-optimized clean text
2. **Data Output** (`structured/data/`) - RAG/analysis with full metadata
3. **Archive Output** (`structured/archive/`) - Complete human-readable markdown

## Directory Structure

```
structured/
├── reading/                    # Output 1: TTS-optimized
│   ├── full_book.txt          # Clean reading text (body only)
│   ├── metadata.json          # Chapter markers for navigation
│   └── page_mapping.json      # Scan page → book page
│
├── data/                       # Output 2: RAG/analysis
│   ├── document_map.json      # Complete structure overview
│   ├── page_mapping.json      # Scan → book page numbers
│   ├── body/                  # Main content
│   │   ├── chapter_01.json
│   │   ├── chapter_02.json
│   │   └── section_01_01.json
│   ├── front_matter/          # Preface, ToC, acknowledgments
│   │   ├── preface.json
│   │   ├── acknowledgments.json
│   │   └── introduction.json
│   └── back_matter/           # Reference material
│       ├── notes.json         # All footnotes/endnotes with refs
│       ├── bibliography.json  # Full structured entries
│       └── appendices/
│           └── appendix_A.json
│
└── archive/                    # Output 3: Complete archive
    └── full_book.md           # Everything, formatted markdown
```

## Schema Definitions

### 1. Document Map (`data/document_map.json`)

High-level structure of the entire book:

```json
{
  "book": {
    "title": "The Accidental President",
    "author": "A. J. Baime",
    "publisher": "HarperCollins",
    "year": 2017,
    "total_pages": 447,
    "isbn": "9780544617346"
  },
  "structure": {
    "front_matter": {
      "start_page": 1,
      "end_page": 8,
      "sections": [
        {
          "type": "title_page",
          "pages": [1, 3]
        },
        {
          "type": "copyright",
          "pages": [4]
        },
        {
          "type": "dedication",
          "pages": [5]
        },
        {
          "type": "contents",
          "pages": [6]
        },
        {
          "type": "introduction",
          "pages": [7, 8]
        }
      ]
    },
    "body": {
      "start_page": 9,
      "end_page": 354,
      "chapter_count": 5,
      "footnote_style": "endnotes_per_chapter"
    },
    "back_matter": {
      "start_page": 355,
      "end_page": 447,
      "sections": [
        {
          "type": "epilogue",
          "pages": [355, 360]
        },
        {
          "type": "acknowledgments",
          "pages": [361, 362]
        },
        {
          "type": "notes",
          "pages": [363, 422]
        },
        {
          "type": "index",
          "pages": [423, 447]
        }
      ]
    }
  },
  "processing": {
    "date": "2025-09-30T10:15:48.453268",
    "model": "anthropic/claude-sonnet-4.5",
    "cost_usd": 0.503397,
    "schema_version": "2.0"
  }
}
```

### 2. Page Mapping (`page_mapping.json`)

Maps scan pages to book page numbers for proper citations:

```json
{
  "mapping": [
    {
      "scan_page": 1,
      "book_page": null,
      "section": "front_matter",
      "section_type": "title_page"
    },
    {
      "scan_page": 7,
      "book_page": "i",
      "section": "front_matter",
      "section_type": "introduction"
    },
    {
      "scan_page": 9,
      "book_page": "1",
      "section": "body",
      "chapter": 1
    },
    {
      "scan_page": 354,
      "book_page": "346",
      "section": "body",
      "chapter": 5
    },
    {
      "scan_page": 355,
      "book_page": null,
      "section": "back_matter",
      "section_type": "epilogue"
    },
    {
      "scan_page": 423,
      "book_page": null,
      "section": "back_matter",
      "section_type": "index"
    }
  ],
  "citation_format": "{author}. *{title}*. {publisher}, {year}. p. {book_page}.",
  "citation_example": "Baime, A. J. *The Accidental President*. HarperCollins, 2017. p. 42."
}
```

### 3. Chapter Structure (`data/body/chapter_XX.json`)

Structured chapter with content type tagging:

```json
{
  "chapter": 1,
  "title": "April 12, 1945",
  "start_page": 9,
  "end_page": 46,
  "start_book_page": "1",
  "end_book_page": "38",
  "summary": "The day Franklin Roosevelt died and Harry Truman became president. Covers Truman's routine day as vice president, Roosevelt's final hours at Warm Springs, the shocking news of FDR's death, and Truman's hurried oath of office at the White House.",
  "sections": [
    {
      "section_id": "ch01_s01",
      "title": null,
      "start_page": 9,
      "end_page": 15,
      "paragraphs": [
        {
          "id": "ch01_s01_p001",
          "text": "On the afternoon of April 12, 1945...",
          "scan_pages": [9],
          "book_page": "1",
          "type": "body",
          "has_footnote": false
        },
        {
          "id": "ch01_s01_p002",
          "text": "Meanwhile, in Warm Springs, Georgia...",
          "scan_pages": [9, 10],
          "book_page": "1-2",
          "type": "body",
          "has_footnote": true,
          "footnote_refs": [1]
        }
      ]
    }
  ],
  "notes": [
    {
      "note_id": 1,
      "text": "Roosevelt had been at Warm Springs since March 30...",
      "cited_in": ["ch01_s01_p002"],
      "source_page": 363,
      "type": "endnote"
    }
  ],
  "word_count": 8234,
  "paragraph_count": 42
}
```

### 4. Bibliography Structure (`data/back_matter/bibliography.json`)

Structured bibliography entries for citation analysis:

```json
{
  "bibliography": [
    {
      "id": 1,
      "author": "Rhodes, Richard",
      "title": "The Making of the Atomic Bomb",
      "publisher": "Simon & Schuster",
      "year": 1986,
      "pages": 886,
      "type": "book",
      "cited_on_book_pages": ["23", "45", "67"],
      "citation_count": 3
    },
    {
      "id": 2,
      "author": "Truman, Harry S.",
      "title": "Memoirs: Year of Decisions",
      "publisher": "Doubleday",
      "year": 1955,
      "pages": 596,
      "type": "book",
      "cited_on_book_pages": ["12", "34", "56", "78", "90"],
      "citation_count": 5
    },
    {
      "id": 3,
      "author": "Stimson, Henry L.",
      "title": "The Decision to Use the Atomic Bomb",
      "publication": "Harper's Magazine",
      "year": 1947,
      "type": "article",
      "cited_on_book_pages": ["145"],
      "citation_count": 1
    }
  ],
  "summary": {
    "total_sources": 3,
    "books": 2,
    "articles": 1,
    "total_citations": 9,
    "most_cited": {
      "author": "Truman, Harry S.",
      "title": "Memoirs: Year of Decisions",
      "citations": 5
    }
  }
}
```

### 5. Notes Structure (`data/back_matter/notes.json`)

All footnotes and endnotes with location metadata:

```json
{
  "notes": [
    {
      "note_id": 1,
      "chapter": 1,
      "text": "Roosevelt had been at Warm Springs since March 30, 1945, seeking rest and recuperation.",
      "cited_in_paragraphs": ["ch01_s01_p002"],
      "book_page_location": "1",
      "scan_page_location": 9,
      "note_source_page": 363,
      "type": "endnote",
      "bibliography_refs": [1, 2]
    },
    {
      "note_id": 2,
      "chapter": 1,
      "text": "Truman was presiding over the Senate in his capacity as vice president.",
      "cited_in_paragraphs": ["ch01_s01_p003"],
      "book_page_location": "2",
      "scan_page_location": 10,
      "note_source_page": 363,
      "type": "endnote",
      "bibliography_refs": [2]
    }
  ],
  "summary": {
    "total_notes": 2,
    "by_chapter": {
      "1": 45,
      "2": 67,
      "3": 89,
      "4": 56,
      "5": 43
    }
  }
}
```

### 6. Reading Text Metadata (`reading/metadata.json`)

Navigation metadata for TTS reading:

```json
{
  "book": {
    "title": "The Accidental President",
    "author": "A. J. Baime"
  },
  "chapters": [
    {
      "number": 1,
      "title": "April 12, 1945",
      "start_position": 0,
      "end_position": 42834,
      "duration_estimate_minutes": 45,
      "word_count": 8234
    },
    {
      "number": 2,
      "title": "The Political Education of Harry S. Truman",
      "start_position": 42835,
      "end_position": 98234,
      "duration_estimate_minutes": 67,
      "word_count": 12345
    }
  ],
  "reading_notes": {
    "footnotes": "collected_at_chapter_end",
    "front_matter_excluded": ["copyright", "contents"],
    "back_matter_excluded": ["index"],
    "total_word_count": 98234,
    "estimated_reading_time_hours": 8.5
  }
}
```

### 7. Reading Text Format (`reading/full_book.txt`)

Clean, TTS-optimized text:

```
The Accidental President
by A. J. Baime

=== Chapter 1: April 12, 1945 ===

On the afternoon of April 12, 1945, Vice President Harry S. Truman was on Capitol Hill...

[Main content continues...]

--- Chapter 1 Notes ---

[1] Roosevelt had been at Warm Springs since March 30, 1945, seeking rest and recuperation.

[2] Truman was presiding over the Senate in his capacity as vice president.

=== Chapter 2: The Political Education of Harry S. Truman ===

[Content continues...]
```

## Content Type Taxonomy

The structure stage classifies content into these types:

### Front Matter
- `title_page` - Book title, author
- `copyright` - Copyright, publishing info
- `dedication` - Dedication page
- `epigraph` - Epigraph or quote
- `contents` - Table of contents
- `foreword` - Foreword by another author
- `preface` - Author's preface
- `acknowledgments` - Acknowledgments (if before body)
- `introduction` - Introduction to the book
- `prologue` - Prologue/opening narrative

### Body
- `body` - Main narrative content
- `chapter_title` - Chapter title and subtitle
- `section_break` - Section dividers within chapters
- `block_quote` - Extended quotations
- `footnote_marker` - Inline footnote references

### Back Matter
- `epilogue` - Concluding narrative
- `conclusion` - Final analysis/summary
- `afterword` - Author's reflection
- `acknowledgments` - Acknowledgments (if after body)
- `appendix` - Supplementary material
- `notes` - Footnotes/endnotes section
- `bibliography` - List of sources
- `index` - Subject index
- `glossary` - Term definitions
- `about_author` - Author biography

## Detection Strategies

### Phase 1: Document Boundaries

LLM analyzes the complete book to identify:

1. **Front matter end** - First page of Chapter 1/main narrative
2. **Body end** - Last page of final chapter
3. **Back matter sections** - Notes, bibliography, index boundaries

Signals for detection:
- Page numbering changes (roman → arabic)
- "Chapter 1" or "Part I" headings
- "Notes", "Bibliography", "Index" headings
- Formatting patterns (two-column index layout)
- Content patterns (alphabetical ordering in index)

### Phase 2: Content Classification

LLM classifies each section by type:

1. **Title/copyright** - Publishing metadata
2. **TOC** - Structured chapter list
3. **Body chapters** - Main narrative with start/end pages
4. **Notes section** - Footnotes/endnotes with chapter organization
5. **Bibliography** - Source citations
6. **Index** - Alphabetical subject index (discard)

### Phase 3: Page Number Extraction

LLM extracts page numbers from each page:

1. Look for numbers in headers/footers
2. Detect roman numeral sequences (front matter)
3. Detect arabic number sequences (body)
4. Identify restarts or special sequences
5. Map scan_page → book_page for all content

### Phase 4: Footnote Normalization

LLM processes notes:

1. **Identify style**: Inline footnotes, chapter endnotes, or book endnotes
2. **Extract**: Parse note text and link to source location
3. **Normalize**: Convert all to chapter-end endnotes for reading output
4. **Preserve**: Keep original locations for structured data
5. **Link**: Connect notes to bibliography entries

## Validation Rules

The structure stage validates:

1. **Completeness**: All scan pages mapped to structure
2. **Continuity**: No page gaps in chapters
3. **Consistency**: Chapter page ranges don't overlap
4. **Notes**: All footnote references have corresponding notes
5. **Bibliography**: All cited sources exist in bibliography
6. **Page mapping**: Scan pages map to valid book pages
7. **Content types**: All sections have valid type tags

## Migration from v1.0

Existing books can be reprocessed by:

1. Reading corrected pages (unchanged input)
2. Running new multi-phase structure detection
3. Generating three-output structure
4. Preserving original v1.0 output as backup (optional)

No data loss occurs as corrected pages remain the source of truth.

## Future Enhancements

Potential future additions:

1. **Figure/table detection** - Extract images and tables separately
2. **Citation linking** - Link in-text citations to bibliography
3. **Cross-references** - Track "see Chapter 3" references
4. **Named entities** - Tag people, places, organizations
5. **Timeline extraction** - Extract dates and events
6. **Quote attribution** - Link quotes to speakers
7. **Multi-volume support** - Handle book series/volumes
