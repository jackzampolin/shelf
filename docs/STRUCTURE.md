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
┌──────────────────────────────────────────────────────────────┐
│ Phase 1: SLIDING WINDOW EXTRACTION ✅ COMPLETE               │
│ (GPT-4o-mini, parallel - 3-agent pattern)                   │
│ • Input: Overlapping page batches (3 pages, 1 overlap)      │
│ • Extract: Clean text + markers (extract_agent)             │
│ • Verify: Full-text LLM quality check (verify_agent)        │
│ • Reconcile: LLM arbitration for overlaps (reconcile_agent) │
│ • Parallelization: 30 workers, ~318 batches (636 pages)     │
│ • Storage: Batch results → structured/extraction/           │
│ • Python counts facts, LLM judges quality                   │
│ • Time: ~5-7 minutes (includes verification + arbitration)  │
│ • Cost: ~$3.18 (~$0.01/batch)                               │
└──────────────────────────────────────────────────────────────┘
                            ↓
┌──────────────────────────────────────────────────────────────┐
│ Phase 2: ASSEMBLY & CHUNKING ✅ COMPLETE                     │
│ (GPT-4o-mini + Python)                                       │
│ • Load batches from structured/extraction/                   │
│ • Merge with reconciled overlaps                             │
│ • Build document map from chapter evidence (bottom-up)      │
│ • Create semantic chunks for RAG (500-1000 words)           │
│ • Generate three output formats                              │
│ • Verify completeness                                        │
│ • Time: ~1-2 minutes                                         │
│ • Cost: ~$0.50                                               │
└──────────────────────────────────────────────────────────────┘

Total: ~6-9 minutes, ~$3.68 per 636-page book
```

---

## Phase 1: Sliding Window Extraction ✅ COMPLETE

**Goal:** Extract clean body text in parallel batches, removing running headers while preserving all substantive content.

### Window Configuration

```python
WINDOW_SIZE = 3       # pages per batch (changed from 10 for reliability)
OVERLAP = 1           # page of overlap between batches
STRIDE = 2            # pages to advance per batch (window_size - overlap)
MAX_WORKERS = 30      # parallel batch processing
```

**For 636-page book:**
```
Batch 1:   pages [1, 2, 3]
Batch 2:   pages [3, 4, 5]             ← overlap: page 3
Batch 3:   pages [5, 6, 7]             ← overlap: page 5
...
Batch 318: pages [634, 635, 636]

Total batches: 318 (stride of 2 pages)
Processing: All 318 batches in parallel with 30 workers
Actual time: ~5-7 minutes (includes full verification + LLM arbitration)
Actual cost: ~$3.18 (~$0.01 per batch)
```

**Why 3-page batches?**
- **Reliability**: Shorter JSON responses = fewer parse errors (100% vs 50% success)
- **Full-text verification**: 3 pages fits in LLM context for complete comparison
- **Better error detection**: 318 overlap points vs 91 = more quality checks

**Why overlap?**
- Verifies consistency (same pages extracted twice should match)
- Enables LLM arbitration when batches disagree on page boundaries
- Provides context at boundaries (chapter transitions, split footnotes)

### 3-Agent Pattern (Like OCR Stage)

**Agent 1: EXTRACTOR (GPT-4o-mini)**

```python
def extract_batch(pages: List[Dict]) -> Dict:
    """Extract clean content from one batch (3 pages)."""

    # Concatenate pages with [PAGE N] markers
    batch_text = concatenate_pages_with_markers(pages)

    system_prompt = """You are a book text extractor.
    Remove repetitive headers/footers while preserving all body content."""

    user_prompt = f"""Extract clean text from pages {start}-{end}.

INPUT: {batch_text}

INSTRUCTIONS:
1. Remove running headers (e.g., "CHAPTER 3", page numbers, book title)
2. Preserve ALL body text, footnotes, captions
3. Maintain paragraph structure
4. Focus on page boundaries - text flows across pages naturally
5. Assign paragraphs to page where they START

Return JSON:
{{
  "clean_text": "extracted text (paragraphs separated by \\n\\n)",
  "paragraphs": [
    {{ "text": "...", "scan_page": 78, "type": "body" }}
  ],
  "running_header_pattern": "pattern removed",
  "chapter_markers": [{{"chapter": 3, "scan_page": 78}}],
  "footnotes": [{{"number": "1", "scan_page": 78}}]
}}

NOTE: scan_page MUST be integer, NOT string.
DO NOT include word_count (Python will calculate).
"""

    response = llm_call("gpt-4o-mini", system_prompt, user_prompt)
    result = parse_json(response)

    # Python calculates word count (don't trust LLM to count!)
    result['word_count'] = len(result['clean_text'].split())
    result['scan_pages'] = [p['page_number'] for p in pages]

    return result
```

**Agent 2: VERIFIER (GPT-4o-mini)**

```python
def verify_extraction(original_pages: List[Dict],
                     extraction_result: Dict) -> Dict:
    """Verify extraction quality using FULL-TEXT comparison."""

    # Build COMPLETE original text (all 3 pages)
    original_full_text = concatenate_pages_with_markers(original_pages)
    extracted_text = extraction_result['clean_text']

    # Python calculates word counts (facts for LLM)
    original_word_count = len(original_full_text.split())
    extracted_word_count = len(extracted_text.split())
    word_count_ratio = extracted_word_count / original_word_count

    system_prompt = """You are a text extraction quality specialist.
    Compare COMPLETE original vs extracted text to verify quality."""

    user_prompt = f"""Verify this extraction by comparing full texts.

<original_text>
Pages: 3
Word count: {original_word_count}
FULL TEXT:
{original_full_text}
</original_text>

<extracted_text>
Word count: {extracted_word_count}
Ratio: {word_count_ratio:.1%}
FULL TEXT:
{extracted_text}
</extracted_text>

<verification_task>
1. Were headers removed correctly? List what was removed.
2. Was body text preserved completely?
3. Does the {word_count_ratio:.1%} ratio make sense?
4. Overall assessment?
</verification_task>

Return JSON:
{{
  "quality_score": 0.95,
  "headers_removed_correctly": true,
  "body_text_preserved": true,
  "issues": [],
  "headers_identified": ["CHAPTER 3", "PAGE 78"],
  "confidence": "high",
  "needs_review": false
}}
"""

    response = llm_call("gpt-4o-mini", system_prompt, user_prompt)
    result = parse_json(response)

    # Add Python-calculated metrics
    result['word_count_ratio'] = word_count_ratio
    result['original_word_count'] = original_word_count
    result['extracted_word_count'] = extracted_word_count

    return result
```

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

## Implementation Status

- [x] Phase 1: Sliding window extractor with 3-agent verification
- [x] Phase 2: Batch merger and semantic chunker
- [x] Output generators (reading, data, archive)
- [x] Provenance tracking (chunk → scan pages)
- [x] Verification checkpoints
- [x] Integration with `ar structure` command
- [x] Validated on Roosevelt autobiography (636 pages, 92% accuracy)
- [x] Documentation for architecture and phases

**Status:** ✅ Complete and production-ready

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
