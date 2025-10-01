# AR Research Output Schema Documentation

**Schema Version:** 2.0
**Last Updated:** 2025-01-15

This document describes the **actual** data structures produced by the AR Research pipeline. All schemas are based on the current implementation, not aspirational features.

---

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [OCR Stage Output](#ocr-stage-output)
4. [Correction Stage Output](#correction-stage-output)
5. [Fix Stage Output](#fix-stage-output)
6. [Structure Stage Output](#structure-stage-output)
7. [Use Case Guide](#use-case-guide)
8. [Current Limitations](#current-limitations)

---

## Overview

The pipeline produces outputs in **four stages**, each building on the previous:

| Stage | Input | Output | Purpose |
|-------|-------|--------|---------|
| 1. OCR | PDF pages | `ocr/page_*.json` | Region-based layout analysis |
| 2. Correction | OCR JSON | `corrected/page_*.json` | 3-agent LLM error correction |
| 3. Fix | Flagged pages | Updated `corrected/page_*.json` | Agent 4 targeted fixes |
| 4. Structure | Corrected pages | `structured/*` (3 formats) | TTS, RAG, and human reading outputs |

**Key Principle:** Each stage preserves all previous data and adds new fields. The OCR structure remains intact through all stages.

---

## Directory Structure

After full pipeline processing:

```
~/Documents/book_scans/<scan-id>/
├── source/                  # Original PDFs
│   └── combined.pdf
├── ocr/                     # Stage 1: Raw OCR
│   ├── page_0001.json
│   ├── page_0002.json
│   └── ...
├── images/                  # Extracted images
│   ├── page_0001_img_001.png
│   └── ...
├── corrected/               # Stage 2-3: LLM corrected
│   ├── page_0001.json       (includes agent4_fixes if flagged)
│   ├── page_0002.json
│   └── ...
├── needs_review/            # Flagged pages (copied from corrected/)
│   ├── page_0042.json
│   └── ...
├── structured/              # Stage 4: Three output formats
│   ├── reading/             # TTS-optimized
│   ├── data/                # RAG/analysis
│   ├── archive/             # Human reading
│   └── metadata.json
└── logs/                    # Processing logs
    ├── ocr.log
    ├── correct.log
    ├── fix.log
    └── structure.log
```

---

## OCR Stage Output

### Location
`ocr/page_0001.json`, `ocr/page_0002.json`, etc. (zero-padded 4 digits)

### Schema

```json
{
  "page_number": 42,
  "page_dimensions": {
    "width": 2550,
    "height": 3300
  },
  "ocr_timestamp": "2025-01-15T10:30:45.123456",
  "ocr_mode": "structured",
  "regions": [
    {
      "id": 1,
      "type": "header",
      "bbox": [100, 50, 500, 30],
      "text": "Chapter Title",
      "confidence": 0.95,
      "reading_order": 1
    },
    {
      "id": 2,
      "type": "body",
      "bbox": [100, 200, 2000, 1500],
      "text": "Main paragraph text...",
      "confidence": 0.92,
      "reading_order": 2
    },
    {
      "id": 3,
      "type": "image",
      "bbox": [150, 1000, 800, 600],
      "image_file": "page_0042_img_003.png",
      "reading_order": 3
    },
    {
      "id": 4,
      "type": "caption",
      "bbox": [150, 1800, 400, 50],
      "text": "LIBRARY OF CONGRESS",
      "confidence": 0.88,
      "reading_order": 4,
      "associated_image": 3
    },
    {
      "id": 5,
      "type": "footer",
      "bbox": [100, 3100, 500, 30],
      "text": "42",
      "confidence": 0.98,
      "reading_order": 5
    }
  ]
}
```

### Field Descriptions

**Page-level fields:**
- `page_number`: Sequential scan page number (starts at 1)
- `page_dimensions`: Width and height in pixels
- `ocr_timestamp`: ISO 8601 timestamp
- `ocr_mode`: Always `"structured"` (region-based layout analysis)

**Region types:**
- `header`: Top 8% of page
- `footer`: Bottom 5% of page
- `body`: Main text regions (default)
- `caption`: ALL CAPS text with museum/library keywords (e.g., "LIBRARY OF CONGRESS")
- `image`: Detected image regions

**Region fields:**
- `id`: Unique ID within page
- `type`: One of the 5 types above
- `bbox`: `[x, y, width, height]` in pixels
- `text`: OCR'd text (for text regions)
- `confidence`: 0-1 confidence score (for text regions)
- `reading_order`: Top-to-bottom, left-to-right sequence
- `image_file`: Filename in `images/` directory (for image regions)
- `associated_image`: ID of associated image (for caption regions)

---

## Correction Stage Output

### Location
`corrected/page_0001.json`, `corrected/page_0002.json`, etc.

### Schema

The correction stage **preserves all OCR data** and adds a `llm_processing` section:

```json
{
  "page_number": 42,
  "page_dimensions": { "width": 2550, "height": 3300 },
  "ocr_timestamp": "2025-01-15T10:30:45.123456",
  "ocr_mode": "structured",
  "regions": [ /* SAME AS OCR STAGE */ ],

  "llm_processing": {
    "timestamp": "2025-01-15T11:45:30.789012",
    "model": "openai/gpt-4o-mini",

    "error_catalog": {
      "page_number": 42,
      "total_errors_found": 5,
      "processing_timestamp": "2025-01-15T11:45:25.123456",
      "errors": [
        {
          "error_id": 1,
          "location": "paragraph 2",
          "original_text": "tbe",
          "error_type": "character_substitution",
          "confidence": 0.95,
          "suggested_correction": "the",
          "context_before": "walked into ",
          "context_after": " room"
        }
      ]
    },

    "corrected_text": "Chapter Title\n\nMain paragraph text with corrections[CORRECTED:1]...",

    "verification": {
      "page_number": 42,
      "all_corrections_applied": true,
      "corrections_verified": {
        "correctly_applied": 5,
        "incorrectly_applied": 0,
        "missed": 0
      },
      "missed_corrections": [],
      "incorrectly_applied": [],
      "unauthorized_changes": [],
      "new_errors_introduced": [],
      "structure_preserved": true,
      "confidence_score": 1.0,
      "needs_human_review": false,
      "review_reason": "",
      "verification_timestamp": "2025-01-15T11:45:30.456789"
    }
  }
}
```

### LLM Processing Fields

**Agent 1 (Error Detection):** `error_catalog`
- `total_errors_found`: Count of detected errors
- `errors`: Array of error objects with location, type, suggested fix

**Agent 2 (Correction):** `corrected_text`
- Plain text string with all regions concatenated
- Includes `[CORRECTED:N]` markers where fixes were applied

**Agent 3 (Verification):** `verification`
- `all_corrections_applied`: Boolean
- `corrections_verified`: Counts of correct/incorrect/missed corrections
- `missed_corrections`: **Structured array** of corrections Agent 2 missed:
  ```json
  {
    "error_id": 3,
    "original_text": "text that should have been changed",
    "should_be": "what it should be",
    "location": "paragraph 5"
  }
  ```
- `incorrectly_applied`: **Structured array** of incorrect changes:
  ```json
  {
    "error_id": 7,
    "was_changed_to": "what Agent 2 incorrectly changed it to",
    "should_be": "what it should actually be",
    "reason": "why the change was wrong"
  }
  ```
- `confidence_score`: 0-1 confidence in corrections
- `needs_human_review`: Boolean flag
- `review_reason`: Explanation if flagged for review

### Skipped Pages

Pages with no correctable text (e.g., image-only pages):

```json
{
  "page_number": 42,
  "page_dimensions": { /* ... */ },
  "ocr_mode": "structured",
  "regions": [ /* ... */ ],

  "llm_processing": {
    "skipped": true,
    "skip_reason": "no_correctable_regions",
    "timestamp": "2025-01-15T11:45:30.789012"
  }
}
```

### Flagged Pages

If `verification.needs_human_review == true` OR `confidence_score < 0.8`, the entire page JSON is **copied** to:

`needs_review/page_0042.json`

These pages are processed by Agent 4 in the Fix stage.

---

## Fix Stage Output

### Location
**Same as Correction stage:** `corrected/page_0001.json` (**updated in-place**)

### Schema

Agent 4 adds a new section to existing `llm_processing`:

```json
{
  "page_number": 42,
  "page_dimensions": { /* ... */ },
  "regions": [ /* ... */ ],

  "llm_processing": {
    "timestamp": "2025-01-15T11:45:30.789012",
    "model": "openai/gpt-4o-mini",
    "error_catalog": { /* Agent 1 */ },
    "corrected_text": "Original Agent 2 text...",
    "verification": { /* Agent 3 */ },

    "agent4_fixes": {
      "timestamp": "2025-01-15T12:15:45.123456",
      "missed_corrections": [
        {
          "error_id": 3,
          "original_text": "presideut",
          "should_be": "president",
          "location": "paragraph 5"
        }
      ],
      "fixed_text": "Final corrected text with additional fixes[FIXED:A4-1]...",
      "agent3_feedback": "Original review reason from Agent 3"
    }
  }
}
```

### Agent 4 Fields

- `missed_corrections`: Copy of corrections from Agent 3 that were addressed
- `fixed_text`: Final corrected text with `[FIXED:A4-N]` markers
- `agent3_feedback`: Original review reason that triggered the fix

### Error Handling

If Agent 4 fails:

```json
{
  "agent4_fixes": {
    "timestamp": "2025-01-15T12:15:45.123456",
    "error": "Error message",
    "status": "failed"
  }
}
```

---

## Structure Stage Output

The structure stage generates **three separate output formats** optimized for different use cases:

1. **`reading/`** - TTS-optimized clean text
2. **`data/`** - Structured JSON for RAG/analysis
3. **`archive/`** - Complete markdown for human reading

### 1. Reading Output (`structured/reading/`)

**Purpose:** Text-to-speech and sequential reading

#### `reading/full_book.txt`

Plain text, body chapters only, footnotes collected at chapter end:

```
The Accidental President
by A.J. Baime

=== Chapter 1: The Happiest Day ===

[full page 1 text]

[full page 2 text]

...

--- Chapter Notes ---

[1] Footnote text here
[2] Another footnote

=== Chapter 2: Title ===

...
```

**Exclusions:**
- Front matter (except title/author)
- Back matter (except notes integrated into chapters)
- Index

#### `reading/metadata.json`

```json
{
  "book": {
    "title": "The Accidental President",
    "author": "A.J. Baime"
  },
  "chapters": [
    {
      "number": 1,
      "title": "The Happiest Day",
      "start_position": 1234,
      "end_position": 5678,
      "duration_estimate_minutes": 25,
      "word_count": 5000
    }
  ],
  "reading_notes": {
    "footnotes": "collected_at_chapter_end",
    "front_matter_excluded": ["title_page", "copyright", "contents"],
    "back_matter_excluded": ["index"],
    "total_word_count": 125000,
    "estimated_reading_time_hours": 10.4
  }
}
```

**Field descriptions:**
- `start_position`/`end_position`: Character offsets in `full_book.txt`
- `duration_estimate_minutes`: Assumes 200 words/minute reading speed
- `estimated_reading_time_hours`: Total word count ÷ 12,000

#### `reading/page_mapping.json`

```json
{
  "mapping": [
    {
      "scan_page": 1,
      "book_page": "i",
      "section": "front_matter",
      "section_type": "title_page"
    },
    {
      "scan_page": 15,
      "book_page": "1",
      "section": "body",
      "chapter": 1
    }
  ],
  "citation_format": "{author}. *{title}*. {publisher}, {year}. p. {book_page}.",
  "citation_example": "Baime, A.J. *The Accidental President*. Houghton Mifflin, 2017. p. 42."
}
```

**Use case:** Convert scan page references to proper book page citations.

---

### 2. Data Output (`structured/data/`)

**Purpose:** RAG systems, semantic search, structured analysis

#### `data/document_map.json`

Master document structure overview:

```json
{
  "book": {
    "title": "The Accidental President",
    "author": "A.J. Baime",
    "publisher": "Houghton Mifflin Harcourt",
    "year": 2017,
    "isbn": "978-0544617346",
    "total_scan_pages": 447
  },

  "front_matter": {
    "start_page": 1,
    "end_page": 14,
    "sections": [
      {
        "type": "title_page",
        "start_page": 1,
        "end_page": 2
      },
      {
        "type": "dedication",
        "start_page": 5,
        "end_page": 5
      },
      {
        "type": "contents",
        "start_page": 7,
        "end_page": 10
      },
      {
        "type": "introduction",
        "start_page": 11,
        "end_page": 14
      }
    ]
  },

  "body": {
    "start_page": 15,
    "end_page": 380,
    "footnote_style": "book_endnotes",
    "chapters": [
      {
        "number": 1,
        "title": "The Happiest Day",
        "start_page": 15,
        "end_page": 25,
        "summary": "FDR's final days and sudden death in April 1945..."
      }
    ]
  },

  "back_matter": {
    "start_page": 381,
    "end_page": 447,
    "sections": [
      {
        "type": "acknowledgments",
        "start_page": 381,
        "end_page": 383
      },
      {
        "type": "notes",
        "start_page": 384,
        "end_page": 425
      },
      {
        "type": "bibliography",
        "start_page": 426,
        "end_page": 440
      },
      {
        "type": "index",
        "start_page": 441,
        "end_page": 447
      }
    ]
  },

  "processing": {
    "date": "2025-01-15T14:30:00.123456",
    "model": "anthropic/claude-sonnet-4.5",
    "cost_usd": 0.45,
    "schema_version": "2.0"
  }
}
```

**Valid section types:**
- **Front matter:** `title_page`, `copyright`, `dedication`, `epigraph`, `contents`, `foreword`, `preface`, `acknowledgments`, `introduction`, `prologue`
- **Back matter:** `epilogue`, `conclusion`, `afterword`, `appendix`, `notes`, `bibliography`, `index`, `glossary`, `about_author`

#### `data/page_mapping.json`

Identical to `reading/page_mapping.json` (saved to both locations for convenience).

#### `data/body/chapter_01.json`

**CRITICAL:** Each "paragraph" is actually **one full page** of text.

```json
{
  "chapter": 1,
  "title": "The Happiest Day",
  "start_page": 15,
  "end_page": 25,
  "summary": "FDR's final days and sudden death in April 1945...",
  "paragraphs": [
    {
      "id": "ch01_p001",
      "text": "[full cleaned text from scan page 15]",
      "scan_pages": [15],
      "type": "body"
    },
    {
      "id": "ch01_p002",
      "text": "[full cleaned text from scan page 16]",
      "scan_pages": [16],
      "type": "body"
    }
  ],
  "word_count": 5432,
  "paragraph_count": 11,
  "notes": [
    {
      "note_id": 1,
      "chapter": 1,
      "text": "Full footnote text...",
      "source_page": 384
    }
  ]
}
```

**Important notes:**
- `paragraphs` array: **One entry per scan page** (NOT semantic paragraphs)
- `id` format: `ch{chapter:02d}_p{page_index:03d}`
- `scan_pages`: Always single-element array `[page_number]`
- `type`: Always `"body"`
- `notes`: Only included if footnotes exist for this chapter

**What this means for RAG:**
- Each "paragraph" is 300-500 words (full page)
- No semantic chunking or overlap
- Each page is independent

#### `data/back_matter/notes.json`

```json
{
  "notes": [
    {
      "note_id": 1,
      "chapter": 1,
      "text": "Full footnote text from notes section...",
      "source_page": 384
    }
  ],
  "summary": {
    "total_notes": 234,
    "by_chapter": {
      "1": 15,
      "2": 18,
      "3": 12
    }
  }
}
```

**Extraction:**
- Uses GPT-4o-mini on notes section
- Processed in parallel chunks (10 pages per chunk)
- Attempts to match footnotes to chapters

#### `data/back_matter/bibliography.json`

```json
{
  "bibliography": [
    {
      "id": 1,
      "author": "McCullough, David",
      "title": "Truman",
      "publisher": "Simon & Schuster",
      "year": 1992,
      "pages": 1120,
      "type": "book"
    },
    {
      "id": 2,
      "author": "Smith, Jean Edward",
      "title": "FDR and the New Deal",
      "publication": "Historical Journal",
      "year": 2007,
      "pages": null,
      "type": "article"
    }
  ],
  "summary": {
    "total_sources": 156,
    "books": 98,
    "articles": 58
  }
}
```

**Extraction:**
- Uses GPT-4o-mini on bibliography section
- Processed in parallel chunks (5 pages per chunk)
- Types: `book` or `article`

#### `data/front_matter/` *(CURRENTLY EMPTY)*

**Note:** Front matter JSON files are **not generated** in the current implementation. Front matter text only appears in:
- `document_map.json` (section boundaries)
- `archive/full_book.md` (full text)

---

### 3. Archive Output (`structured/archive/`)

**Purpose:** Complete book for human reading

#### `archive/full_book.md`

Complete markdown with front matter, body, and back matter:

```markdown
# The Accidental President

**By A.J. Baime**

*Houghton Mifflin Harcourt, 2017*

---

## Front Matter

### Dedication

[dedication page text]

### Introduction

[introduction text]

## Chapter 1: The Happiest Day

*FDR's final days and sudden death in April 1945...*

[full chapter text from all pages]

## Chapter 2: Title

...

## Back Matter

### Acknowledgments

[acknowledgments text]

### Notes

[notes section - raw text, not parsed]

### Bibliography

[bibliography section - raw text, not parsed]
```

**Exclusions:**
- Title page, copyright, table of contents (front matter)
- Index (back matter)

---

### Processing Metadata (`structured/metadata.json`)

High-level processing summary:

```json
{
  "book_slug": "modest-lovelace",
  "book_info": {
    "title": "The Accidental President",
    "author": "A.J. Baime",
    "publisher": "Houghton Mifflin Harcourt",
    "year": 2017
  },
  "processing_date": "2025-01-15T14:35:00.123456",
  "schema_version": "2.0",
  "stats": {
    "pages_loaded": 447,
    "chapters_detected": 22,
    "front_matter_sections": 4,
    "back_matter_sections": 4,
    "page_numbers_extracted": 423,
    "footnotes_extracted": 234,
    "bibliography_entries": 156,
    "total_cost_usd": 0.5234,
    "phase_costs": {
      "phase_1_2_structure": 0.3456,
      "phase_3_page_numbers": 0.0890,
      "phase_6_footnotes": 0.0456,
      "phase_7_bibliography": 0.0432
    },
    "input_tokens": 145678,
    "output_tokens": 12345
  },
  "chapters": [
    {
      "number": 1,
      "title": "The Happiest Day",
      "pages": [15, 25]
    }
  ]
}
```

---

## Use Case Guide

### For TTS / Audiobook Creation

**Use:** `structured/reading/`

```python
# Read TTS-optimized text
with open("structured/reading/full_book.txt") as f:
    book_text = f.read()

# Get chapter positions
with open("structured/reading/metadata.json") as f:
    metadata = json.load(f)

for chapter in metadata["chapters"]:
    start = chapter["start_position"]
    end = chapter["end_position"]
    chapter_text = book_text[start:end]
    # Send to TTS engine
```

### For RAG / Semantic Search

**Use:** `structured/data/`

```python
# Load all chapters
import json
from pathlib import Path

chapters = []
for chapter_file in Path("structured/data/body").glob("chapter_*.json"):
    with open(chapter_file) as f:
        chapters.append(json.load(f))

# Each "paragraph" is actually one full page
for chapter in chapters:
    for page_paragraph in chapter["paragraphs"]:
        # page_paragraph["text"] contains ~300-500 words
        # page_paragraph["scan_pages"] tells you the source page
        # page_paragraph["id"] is a unique identifier

        # Add to vector database
        embed_and_store(
            text=page_paragraph["text"],
            metadata={
                "chapter": chapter["chapter"],
                "chapter_title": chapter["title"],
                "page_id": page_paragraph["id"],
                "scan_page": page_paragraph["scan_pages"][0]
            }
        )
```

### For Citation / Provenance

**Use:** `structured/data/page_mapping.json`

```python
# Convert scan page to book page for citation
with open("structured/data/page_mapping.json") as f:
    mapping_data = json.load(f)

def get_citation(scan_page: int) -> str:
    for entry in mapping_data["mapping"]:
        if entry["scan_page"] == scan_page:
            book_page = entry["book_page"]
            # Use citation template
            return f"Baime, A.J. *The Accidental President*. Houghton Mifflin, 2017. p. {book_page}."
```

### For Bibliography Research

**Use:** `structured/data/back_matter/bibliography.json`

```python
# Find all sources by an author
with open("structured/data/back_matter/bibliography.json") as f:
    biblio = json.load(f)

mccullough_sources = [
    entry for entry in biblio["bibliography"]
    if "McCullough" in entry["author"]
]
```

### For Full-Text Reading

**Use:** `structured/archive/full_book.md`

Open in any markdown viewer/editor. Contains complete book text including front matter and back matter.

---

## Current Limitations

### 1. "Paragraphs" Are Full Pages

**Limitation:** Chapter JSON files use the term "paragraph" for what is actually **one full page** of text.

**Impact:**
- No semantic paragraph detection within pages
- RAG systems get ~300-500 word chunks (full pages)
- No overlap between chunks

**Workaround:** For finer-grained chunking, parse the `text` field yourself:
```python
page_text = paragraph["text"]
sentences = sent_tokenize(page_text)  # NLTK or spaCy
# Create overlapping chunks from sentences
```

### 2. No RAG-Style Chunking

**Limitation:** No ~5-page semantic chunks with overlap.

**Impact:** Can't query across page boundaries effectively.

**Workaround:** Implement your own chunking:
```python
# Combine consecutive pages with overlap
def create_chunks(chapters, chunk_size=5, overlap=1):
    chunks = []
    for chapter in chapters:
        pages = chapter["paragraphs"]
        for i in range(0, len(pages), chunk_size - overlap):
            chunk_pages = pages[i:i + chunk_size]
            chunk_text = "\n\n".join(p["text"] for p in chunk_pages)
            chunks.append({
                "text": chunk_text,
                "chapter": chapter["chapter"],
                "scan_pages": [p["scan_pages"][0] for p in chunk_pages]
            })
    return chunks
```

### 3. No Section-Level Structure Within Chapters

**Limitation:** Chapters are flat - no sub-sections or hierarchical structure.

**Impact:** Can't query "Section 2 of Chapter 5"

**Workaround:** Use headings in text to detect sections:
```python
# Simple section detection
sections = []
current_section = []
for page in chapter["paragraphs"]:
    if page["text"].startswith("###") or page["text"].isupper():
        if current_section:
            sections.append(current_section)
        current_section = [page]
    else:
        current_section.append(page)
```

### 4. Front Matter JSON Files Not Generated

**Limitation:** `data/front_matter/` directory exists but is empty.

**Impact:** Front matter text only available in `archive/full_book.md` and as boundaries in `document_map.json`.

**Workaround:** Extract from corrected pages:
```python
# Get front matter page range from document_map
with open("structured/data/document_map.json") as f:
    doc_map = json.load(f)

intro_section = next(
    s for s in doc_map["front_matter"]["sections"]
    if s["type"] == "introduction"
)

# Load pages in that range
for page_num in range(intro_section["start_page"], intro_section["end_page"] + 1):
    with open(f"corrected/page_{page_num:04d}.json") as f:
        page = json.load(f)
        intro_text = page["llm_processing"]["corrected_text"]
        # Process intro text
```

### 5. Limited Citation Tracking

**Limitation:** No tracking of which paragraphs cite which footnotes/bibliography entries.

**Impact:** Can't answer "What sources are cited in Chapter 3?"

**Workaround:** Text search for footnote markers:
```python
import re

def find_footnotes_in_text(text: str) -> list[int]:
    # Look for [1], [23], etc.
    matches = re.findall(r'\[(\d+)\]', text)
    return [int(m) for m in matches]

chapter_footnotes = []
for page in chapter["paragraphs"]:
    footnote_ids = find_footnotes_in_text(page["text"])
    chapter_footnotes.extend(footnote_ids)
```

### 6. Correction Markers in Text

**Limitation:** Corrected text includes markers like `[CORRECTED:1]` and `[FIXED:A4-2]`.

**Impact:** Need to strip these for clean reading/TTS.

**Workaround:** Regex cleaning:
```python
import re

def clean_markers(text: str) -> str:
    # Remove [CORRECTED:N] and [FIXED:A4-N] markers
    text = re.sub(r'\[CORRECTED:\d+\]', '', text)
    text = re.sub(r'\[FIXED:A4-\d+\]', '', text)
    return text

clean_text = clean_markers(page["llm_processing"]["corrected_text"])
```

**Note:** The Structure stage already cleans these markers (Phase 0), so `structured/` outputs don't include them.

### 7. Page Number Extraction May Be Incomplete

**Limitation:** Page number extraction has ~95% accuracy, some pages may have `null` book page numbers.

**Impact:** Some scan pages can't be cited properly.

**Check:**
```python
with open("structured/data/page_mapping.json") as f:
    mapping = json.load(f)

missing = [
    entry["scan_page"]
    for entry in mapping["mapping"]
    if entry["book_page"] is None
]
print(f"{len(missing)} pages missing book page numbers")
```

---

## File Naming Conventions

| File Type | Pattern | Example |
|-----------|---------|---------|
| OCR pages | `page_NNNN.json` | `page_0042.json` |
| Corrected pages | `page_NNNN.json` | `page_0042.json` |
| Review pages | `page_NNNN.json` | `page_0042.json` |
| Chapters | `chapter_NN.json` | `chapter_01.json` |
| Images | `page_NNNN_img_NNN.png` | `page_0042_img_003.png` |

**Note:** Page numbers use 4-digit zero-padding, chapter numbers use 2-digit zero-padding.

---

## Schema Version History

**Current:** v2.0

**Changes from v1.0:**
- Moved from batch-based to flat directory structure
- Added structured regions (was "plain" mode before)
- Added multi-phase structure pipeline
- Added three separate output formats (reading/data/archive)
- Added Agent 3 structured arrays (`missed_corrections`, `incorrectly_applied`)
- Added Agent 4 fix stage

---

**Questions or issues with this schema?** Check the source code or file an issue on GitHub.
