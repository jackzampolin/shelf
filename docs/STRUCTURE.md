# Structure Detection and Content Assembly

## Overview

Stage 4 of the Scanshelf pipeline transforms corrected pages into structured book content suitable for reading, RAG, and analysis. Uses a **hybrid approach** combining light structure detection with parallel content extraction.

## Input

**From Stage 3 (Fix):**
- `corrected/page_*.json` files (one per page)
- Each page has regions with corrected text
- Regions marked with `[CORRECTED:id]` and `[FIXED:A4-id]` markers
- Example: 636 pages for Roosevelt autobiography

**Key Challenge:**
- OCR misclassifies body text as "header" regions
- Header regions contain: `"[page#] [RUNNING HEADER] [body text]"`
- Need to extract body text while removing repetitive headers
- Can't use simple region filtering (loses ~25-30% of content)

## Output

**Three formats for different use cases:**

### 1. Reading Text (`structured/reading/`)
TTS-optimized format for audiobook generation:
```
reading/
├── full_book.txt          # Clean text, chapters concatenated
├── metadata.json          # Chapter positions, durations
└── page_mapping.json      # Scan page → book page mapping
```

### 2. Structured Data (`structured/data/`)
JSON format for RAG and analysis:
```
data/
├── document_map.json      # Book metadata, chapter/section boundaries
├── page_mapping.json      # Complete page mapping with sections
├── body/
│   └── chapter_*.json     # Per-chapter with paragraphs, metadata
├── front_matter/
│   └── [section files]
└── back_matter/
    ├── notes.json
    └── bibliography.json
```

### 3. Archive (`structured/archive/`)
Complete markdown for human reading:
```
archive/
└── full_book.md           # Full book in markdown format
```

**Provenance Tracking:**

Each chunk/paragraph tracks its source:
```json
{
  "chunk_id": "ch03_chunk_007",
  "chapter": 3,
  "text": "Roosevelt's experience...",
  "scan_pages": [78, 79, 80],      // PDF pages (for linking)
  "book_pages": ["58", "59", "60"], // Original page numbers
  "word_count": 847,
  "position_in_chapter": 7
}
```

This enables: **Given text → find chunk → get scan_pages → open PDF to exact pages**

---

## Architecture: 2-Phase Bottom-Up Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│ Phase 1: SLIDING WINDOW EXTRACTION (GPT-4o-mini, parallel) │
│ • Input: Overlapping page batches (10 pages, 3 overlap)    │
│ • Extract: Clean text + chapter markers + footnotes        │
│ • Verify: Word counts, overlap consensus (3-agent pattern) │
│ • Parallelization: 30 workers, ~91 batches                 │
│ • Time: 2-3 minutes                                         │
│ • Cost: ~$0.80                                              │
└─────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────┐
│ Phase 2: ASSEMBLY & CHUNKING (GPT-4o-mini + Python)        │
│ • Merge batches (reconcile overlaps)                        │
│ • Build document map from chapter evidence (bottom-up)     │
│ • Create semantic chunks for RAG (500-1000 words)          │
│ • Generate three output formats                             │
│ • Verify completeness                                       │
│ • Time: 30-60 seconds                                       │
│ • Cost: ~$0.30                                              │
└─────────────────────────────────────────────────────────────┘

Total: ~3-4 minutes, ~$1.10 (45% cheaper than old approach)
```

---

## Phase 1: Sliding Window Extraction

**Goal:** Extract clean body text in parallel batches, removing running headers while preserving all substantive content.

### Window Configuration

```python
WINDOW_SIZE = 10      # pages per batch
OVERLAP = 3           # pages of overlap between batches
MAX_WORKERS = 30      # parallel batch processing
```

**For 636-page book:**
```
Batch 1:  pages [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
Batch 2:  pages [8, 9, 10, 11, 12, 13, 14, 15, 16, 17]  ← overlap: 8,9,10
Batch 3:  pages [15, 16, 17, 18, 19, 20, 21, 22, 23, 24]  ← overlap: 15,16,17
...
Batch 91: pages [628, 629, 630, 631, 632, 633, 634, 635, 636]

Total batches: 91 (stride of 7 pages)
Processing: All 91 batches in parallel with 30 workers
Expected time: 2-3 minutes
```

**Why overlap?**
- Verifies consistency (same pages extracted twice should match)
- Provides context at boundaries (chapter transitions, split footnotes)
- Enables error detection (if extractions disagree, flag for review)

### 3-Agent Pattern (Like OCR Stage)

**Agent 1: EXTRACTOR (GPT-4o-mini)**

```python
def extract_batch(pages: List[Dict]) -> Dict:
    """Extract clean content from one batch."""

    # Concatenate all pages in batch
    batch_text = concatenate_pages_with_markers(pages)

    system_prompt = """You are a book text extractor. Extract clean body text from scanned pages, removing repetitive headers/footers while preserving all substantive content."""

    user_prompt = f"""Extract clean body text from pages {pages[0]['page_number']}-{pages[-1]['page_number']}.

INPUT PAGES:
{batch_text}

INSTRUCTIONS:
1. Remove running headers (e.g., "80 THEODORE ROOSEVELT—AN AUTOBIOGRAPHY")
   - Pattern typically: "[page#] [BOOK TITLE]"
   - But KEEP any body text that follows the header on same line
2. Remove page numbers (scan and book page numbers)
3. Remove repetitive footers if present
4. Preserve ALL body text, footnotes, captions
5. Preserve paragraph breaks
6. Note any chapter markers (e.g., "CHAPTER III: ...")

Return JSON:
{{
  "clean_text": "extracted text with paragraphs separated by \\n\\n",
  "paragraphs": [
    {{
      "text": "paragraph text",
      "scan_page": 78,
      "type": "body" | "footnote" | "caption"
    }}
  ],
  "running_header_pattern": "pattern identified and removed",
  "chapter_markers": [
    {{"chapter": 3, "title": "...", "scan_page": 78}}
  ],
  "footnotes": [
    {{"number": 1, "text": "...", "scan_page": 78}}
  ],
  "word_count": 4521
}}
"""

    response = llm_call(system_prompt, user_prompt)
    return parse_response(response)
```

**Agent 2: VERIFIER (GPT-4o-mini)**

```python
def verify_extraction(original_pages: List[Dict],
                     extracted: Dict) -> Dict:
    """Verify extraction quality."""

    # Calculate expected word count
    original_word_count = sum(
        len(p['text'].split()) for p in original_pages
    )
    extracted_word_count = extracted['word_count']

    system_prompt = """Verify content extraction quality. Check for lost content, incorrect header removal, or other issues."""

    user_prompt = f"""Verify this extraction:

ORIGINAL PAGES: {len(original_pages)} pages, ~{original_word_count} words
EXTRACTED: {extracted_word_count} words

ORIGINAL TEXT (first 500 chars):
{original_pages[0]['text'][:500]}

EXTRACTED TEXT (first 500 chars):
{extracted['clean_text'][:500]}

RUNNING HEADER PATTERN REMOVED: {extracted['running_header_pattern']}

Verify:
1. Word count reasonable? (expect 85-95% of original after removing headers/page numbers)
2. No substantive content lost?
3. Header pattern correctly identified?
4. Paragraph breaks preserved?
5. Chapter markers accurately detected?

Return JSON:
{{
  "quality_score": 0.95,  // 0.0-1.0
  "issues": ["issue description if any"],
  "confidence": "high" | "medium" | "low",
  "word_count_ok": true,
  "needs_review": false
}}
"""

    response = llm_call(system_prompt, user_prompt)
    return parse_response(response)
```

**Agent 3: RECONCILER (Python + LLM if needed)**

```python
def reconcile_overlaps(batch1: Dict, batch2: Dict,
                      overlap_pages: List[int]) -> Dict:
    """Merge overlapping regions between adjacent batches."""

    # Extract overlap content from each batch
    batch1_overlap = extract_pages(batch1, overlap_pages)
    batch2_overlap = extract_pages(batch2, overlap_pages)

    # Compare
    if texts_match(batch1_overlap, batch2_overlap, threshold=0.95):
        # Consensus! Use either version
        return {
            'status': 'consensus',
            'overlap_text': batch1_overlap,
            'confidence': 'high'
        }
    else:
        # Disagreement - LLM arbitration
        system_prompt = """Resolve conflicting extractions from overlapping page ranges."""

        user_prompt = f"""Two batches extracted the same pages differently:

BATCH 1 EXTRACTION:
{batch1_overlap}

BATCH 2 EXTRACTION:
{batch2_overlap}

PAGES: {overlap_pages}

Which extraction is more accurate? Or should we merge them?

Return JSON:
{{
  "best_extraction": "batch1" | "batch2" | "merged",
  "merged_text": "text if merged",
  "reason": "explanation"
}}
"""

        response = llm_call(system_prompt, user_prompt)
        return parse_response(response)
```

### Verification Checkpoints

**1. Word Count Check**
```python
original_words = sum(count_words(page) for page in pages)
extracted_words = result['word_count']

expected_ratio = 0.85  # Lost ~15% (headers, page numbers)
if extracted_words < original_words * expected_ratio:
    flag_for_review("Excessive content loss")
```

**2. Overlap Consensus**
```python
for i in range(len(batches) - 1):
    overlap_match = compare_overlaps(batches[i], batches[i+1])
    if overlap_match < 0.95:
        flag_for_review(f"Batches {i} and {i+1} disagree on overlap")
```

**3. Chapter Boundary Verification**
```python
# Compare Phase 1 (light detection) with Phase 2 (extraction)
for chapter in light_detection_chapters:
    extraction_markers = find_chapter_markers(batches, chapter.number)
    if abs(chapter.start_page - extraction_markers.start_page) > 3:
        flag_for_review(f"Chapter {chapter.number} boundary mismatch")
```

**4. Completeness**
```python
# All pages covered?
covered_pages = set()
for batch in batches:
    covered_pages.update(batch['scan_pages'])

if covered_pages != set(range(1, total_pages + 1)):
    raise Exception("Missing pages in extraction")
```

---

## Phase 2: Assembly & Chunking

**Goal:** Merge batches into final outputs with semantic chunking for RAG.

### Batch Merging

```python
def merge_batches(batches: List[Dict]) -> str:
    """Merge overlapping batches into complete book text."""

    merged = []

    for i, batch in enumerate(batches):
        if i == 0:
            # First batch: take everything before overlap
            merged.append(batch.text_before_overlap())
        else:
            # Reconcile overlap with previous batch
            overlap = reconcile_overlaps(
                batches[i-1],
                batch,
                overlap_pages=[batch.start_page-OVERLAP, ..., batch.start_page]
            )
            merged.append(overlap['overlap_text'])
            merged.append(batch.text_after_overlap())

    return '\n\n'.join(merged)
```

### Semantic Chunking for RAG

**Goal:** Split text into semantic units (500-1000 words) that make sense for retrieval.

**Strategy:**
```python
def create_semantic_chunks(chapters: List[Dict]) -> List[Dict]:
    """Create RAG-optimized chunks."""

    chunks = []

    for chapter in chapters:
        # Split chapter into semantic sections
        sections = llm_split_semantically(
            text=chapter['text'],
            target_size=750,  # words
            respect_boundaries=True  # Don't split mid-paragraph
        )

        for i, section in enumerate(sections):
            chunk = {
                "chunk_id": f"ch{chapter['number']:02d}_chunk_{i+1:03d}",
                "chapter": chapter['number'],
                "chapter_title": chapter['title'],
                "text": section['text'],
                "scan_pages": section['scan_pages'],
                "book_pages": section['book_pages'],
                "word_count": section['word_count'],
                "position_in_chapter": i + 1,
                "total_chunks_in_chapter": len(sections)
            }
            chunks.append(chunk)

    return chunks
```

**LLM Prompt for Semantic Splitting:**
```
Split this chapter into semantic sections of ~750 words each.

CHAPTER TEXT:
{chapter_text}

RULES:
1. Target 750 words per section (±200 words ok)
2. Split at natural boundaries (scene changes, topic shifts)
3. Never split mid-paragraph
4. Each section should be self-contained enough for RAG retrieval

Return JSON:
{
  "sections": [
    {
      "text": "section text",
      "start_position": 0,
      "end_position": 4521,
      "word_count": 847,
      "theme": "brief description of what this section covers"
    }
  ]
}
```

### Output Generation

**1. Reading Text** (`structured/reading/full_book.txt`)
```python
# Simple concatenation with chapter markers
reading_text = []
for chapter in chapters:
    reading_text.append(f"=== Chapter {chapter['number']}: {chapter['title']} ===\n")
    reading_text.append(chapter['clean_text'])
    reading_text.append("\n\n")

save('structured/reading/full_book.txt', '\n'.join(reading_text))
```

**2. Structured Data** (`structured/data/`)
```python
# Save per-chapter JSON
for chapter in chapters:
    save(f'structured/data/body/chapter_{chapter["number"]:02d}.json', {
        "chapter": chapter['number'],
        "title": chapter['title'],
        "paragraphs": chapter['paragraphs'],
        "word_count": chapter['word_count'],
        "scan_pages": [chapter['start_page'], chapter['end_page']]
    })

# Save chunks
for chunk in chunks:
    save(f'structured/data/chunks/chunk_{chunk["chunk_id"]}.json', chunk)
```

**3. Archive Markdown** (`structured/archive/full_book.md`)
```python
# Full markdown with formatting
md = []
md.append(f"# {book_title}\n")
md.append(f"**By {book_author}**\n\n")

for chapter in chapters:
    md.append(f"## Chapter {chapter['number']}: {chapter['title']}\n")
    md.append(chapter['clean_text'])
    md.append("\n\n")

save('structured/archive/full_book.md', '\n'.join(md))
```

---

## Cost and Performance

**For 636-page book (Roosevelt autobiography):**

| Phase | Model | Time | Cost | Notes |
|-------|-------|------|------|-------|
| Phase 1: Extraction | GPT-4o-mini | 2-3min | $0.80 | 91 batches × 30 workers |
| Phase 2: Chunking | GPT-4o-mini | 30-60s | $0.30 | Semantic splitting |
| **Total** | | **~3-4min** | **$1.10** | 45% cheaper than old approach |

**Comparison with old approach:**
- Old: Top-down structure ($1.50) + extraction ($0.50) = $2.00, 4-5 minutes
- New: Bottom-up extraction + chunking = $1.10, 3-4 minutes
- **Savings: 45% cost, 20% time**

---

## Implementation Checklist

- [ ] Phase 1: Sliding window extractor with 3-agent verification
- [ ] Phase 2: Batch merger and semantic chunker
- [ ] Output generators (reading, data, archive)
- [ ] Provenance tracking (chunk → scan pages)
- [ ] Verification checkpoints
- [ ] Integration with `ar.py structure` command
- [ ] Tests on Roosevelt autobiography
- [ ] Documentation for each phase

---

## Code Organization

```
pipeline/structure/
├── __init__.py              # Main BookStructurer orchestrator
├── extractor.py            # Phase 1: Sliding window extraction orchestrator
├── assembler.py            # Phase 2: Assembly & chunking orchestrator
├── agents/
│   ├── __init__.py
│   ├── extract_agent.py    # Agent 1: Extract clean text
│   ├── verify_agent.py     # Agent 2: Verify quality
│   └── reconcile_agent.py  # Agent 3: Reconcile overlaps
├── chunker.py              # Semantic chunking logic
├── generator.py            # Output generation (adapted from v1)
└── utils.py                # Shared utilities
```

---

**Related:** See `docs/OCR_CLEAN.md` for stages 1-3 (OCR, correction, fix)
