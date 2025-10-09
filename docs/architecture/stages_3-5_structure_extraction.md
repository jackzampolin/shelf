# Scanshelf Pipeline: Stages 3-5 Architecture
**Structure Extraction: From Corrected Pages to Chapters & Chunks**

**Version:** 1.0
**Date:** 2025-10-09
**Status:** Approved for Implementation
**Related Issue:** [#56 - Pipeline Refactor](https://github.com/jackzampolin/scanshelf/issues/56)

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [Background & Context](#background--context)
3. [Architecture Decisions](#architecture-decisions)
4. [Data Analysis](#data-analysis)
5. [Stage 3: Merge & Enrich](#stage-3-merge--enrich)
6. [Stage 4: Structure Detection](#stage-4-structure-detection)
7. [Stage 5: Chunk Assembly](#stage-5-chunk-assembly)
8. [Data Flow](#data-flow)
9. [Cost & Performance](#cost--performance)
10. [Implementation Roadmap](#implementation-roadmap)
11. [Risks & Mitigations](#risks--mitigations)
12. [Success Criteria](#success-criteria)

---

## Executive Summary

This document defines the architecture for Scanshelf pipeline stages 3-5, which convert corrected page-level data into structured book content (chapters and chunks) suitable for MCP server queries and audiobook generation.

### Key Design Principles

1. **Leverage Existing Labels:** The correction stage (stage 2) already provides excellent semantic labels (CHAPTER_HEADING, TABLE_OF_CONTENTS, PAGE_NUMBER, etc.). We use these labels with minimal LLM intervention.

2. **Page Number Mapping:** Build a mapping between PDF page numbers and book page numbers early in the process. This enables accurate ToC parsing and user-facing features.

3. **Rules-Based + Liberal LLM Validation:** Use deterministic rules for structure extraction, but validate liberally with LLM since text LLM is cheap (~$0.20 for full book).

4. **Maximum Debugability:** Keep full files for each stage (OCR, corrected, processed) to enable debugging and future refinements.

5. **Pragmatic Implementation:** Focus on 80/20 - get the core working with room for future enhancements.

### Three-Stage Architecture

| Stage | Purpose | Input | Output | Cost | Time |
|-------|---------|-------|--------|------|------|
| **3: Merge & Enrich** | Combine OCR + corrections into unified pages | ocr/*.json + corrected/*.json | processed/*.json | $0 | 30s |
| **4: Structure Detection** | Extract page mapping, ToC, and chapter boundaries | processed/*.json | chapters/*.json | $0.20-0.25 | 2-3min |
| **5: Chunk Assembly** | Create ~5-page semantic chunks | processed/*.json + chapters/*.json | chunks/*.json | $0 | 30s |
| **Total** | | | | **$0.20-0.25** | **3-4min** |

### What This Enables

- **MCP Server:** Query by chapter, search full text, retrieve chunks with context
- **Audiobook Generation:** Natural reading flow with chapter awareness and book page references
- **Book Reader UI:** Chapter navigation, progress tracking, accurate page citations
- **RAG Applications:** Semantic chunk retrieval for LLM context

---

## Background & Context

### Pipeline Evolution

The Scanshelf pipeline has undergone major refactoring:

**Stages 0-2 (Completed):**
- **0_ingest:** Extract metadata from PDFs
- **1_ocr:** Vision-based OCR with structured block extraction
- **2_correction:** LLM-based text correction with semantic labeling

**Old Stages 3-6 (Removed):**
- Based on old OCR format (now obsolete)
- Overengineered multi-phase approach
- Estimated cost: $2-5 per book

**New Stages 3-5 (This Document):**
- Designed from scratch based on actual corrected output
- Leverages existing labels from stage 2
- Cost-effective: $0.20-0.25 per book (10-20x cheaper)

### Why Redesign?

The old design had several issues:
1. Based on outdated OCR format assumptions
2. Re-analyzed content already classified by correction stage
3. Complex multi-phase processing (discovery → classification → stitching → assembly)
4. Expensive LLM usage ($2-5 per book)

The new design:
1. Uses actual corrected output format
2. Leverages existing high-quality labels (>95% accuracy)
3. Simple three-stage pipeline
4. Cost-effective ($0.20-0.25 per book)

---

## Architecture Decisions

### Decision 1: Keep Full Files for Each Stage ✅

**Strategy:** Preserve OCR, corrected, AND processed files

```
book_directory/
├── ocr/
│   └── page_XXXX.json          # Raw OCR (preserved)
├── corrected/
│   └── page_XXXX.json          # Corrections + labels (preserved)
├── processed/
│   └── page_XXXX.json          # Merged output (new)
├── chapters/
│   ├── page_mapping.json       # PDF ↔ Book page mapping
│   ├── toc.json                # Parsed table of contents
│   └── chapters.json           # Chapter boundaries
└── chunks/
    ├── manifest.json           # Index of all chunks
    └── chunk_XXXX.json         # Individual chunks
```

**Rationale:**
- Maximum debugability
- Easy to trace data transformations
- Can reprocess stages without losing source data
- Disk space is cheap (~5MB per 400-page book total)

**Trade-off:** 3x disk usage vs. overwriting. Acceptable given low storage cost.

---

### Decision 2: Liberal LLM Validation Strategy ✅

**Strategy:** Don't be conservative with validation - text LLM is cheap

**Validation Approach:**
- Validate ALL chapter boundaries (not just ambiguous ones)
- Could process entire book context for <$0.20
- Better to over-validate than miss edge cases

**Models:**
- Primary: `openai/gpt-4o-mini` ($0.15/1M input tokens, $0.6/1M output tokens)
- Fallback: `anthropic/claude-haiku` (similar pricing)

**Cost Estimate:**
- 400-page book ≈ 200k tokens
- Full validation: ~$0.15-0.20
- Still 10-20x cheaper than old approach

**Rationale:** Quality over cost savings. $0.20 is negligible vs. pipeline value.

---

### Decision 3: Chunk Overlap ⏸️

**Strategy:** Implement as optional parameter, test to see if useful

**Initial Implementation:**
- Default: No overlap (simpler)
- Add `--chunk-overlap=N` parameter for future testing

**Future Testing:**
- Test MCP queries for context issues at chunk boundaries
- Test audiobook generation for awkward pauses
- Enable overlap if benefits justify complexity

**Rationale:** YAGNI - implement when proven necessary.

---

### Decision 4: Front/Back Matter Handling ⏸️

**Strategy:** Include in chunks for now, revisit with dedicated handling later

**Current Approach:**
- Stage 4 identifies front matter (before first chapter) and back matter (after last chapter)
- Include in chunk generation (treated like body content)
- Chunks preserve classification labels (ENDNOTES, INDEX, BIBLIOGRAPHY)

**Future Enhancements:**
- Extract as separate artifacts (preface.json, index.json)
- Special handling for footnotes/endnotes
- Bibliography as structured references

**Rationale:** Get core working first. Labels are preserved for future refinement.

---

### Decision 5: Structured ToC Extraction ✅

**Strategy:** YES - Extract ToC as structured navigation

**Output:** `chapters/toc.json`
```json
{
  "scan_id": "accidental-president",
  "toc_pages": [6, 7],
  "entries": [
    {
      "title": "Part I",
      "level": 0,
      "book_page": null,
      "pdf_page": null,
      "entry_type": "part_heading"
    },
    {
      "title": "April 12, 1945",
      "level": 1,
      "book_page": "3",
      "pdf_page": 9,
      "entry_type": "chapter"
    }
  ]
}
```

**Benefits:**
- Enables MCP "list chapters" queries
- Provides expected structure for validation
- Useful for book reader UI navigation
- Can detect ToC vs. actual chapter mismatches

**Rationale:** High value, low complexity. Essential metadata.

---

### Decision 6: Page Number Mapping ✅ (NEW!)

**Strategy:** Build PDF ↔ Book page mapping early in Stage 4

**Problem Statement:**
- PDF pages: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10... (sequential)
- Book pages: i, ii, iii, iv, v, vi, 1, 2, 3, 4... (front matter → body)
- ToC references use book pages: "Chapter 3 → page 45"
- Without mapping: Can't validate "page 45" against PDF page 51

**Solution:** Extract page numbers from each page, build bidirectional mapping

**Output:** `chapters/page_mapping.json`
```json
{
  "scan_id": "accidental-president",
  "mappings": [
    {"pdf_page": 1, "book_page": null, "page_type": "front_matter"},
    {"pdf_page": 2, "book_page": "i", "page_type": "front_matter"},
    {"pdf_page": 7, "book_page": "1", "page_type": "body"},
    {"pdf_page": 51, "book_page": "45", "page_type": "body"},
    {"pdf_page": 447, "book_page": "442", "page_type": "body"}
  ],
  "front_matter_pages": [1, 2, 3, 4, 5, 6],
  "body_pages": [7, 446],
  "back_matter_pages": [447]
}
```

**Benefits:**
- Accurate ToC cross-validation
- User-facing page numbers (MCP queries, audiobook metadata)
- Better citations and references
- Debugging: "Processing PDF page 51 (book page 45)"

**Rationale:** Foundational infrastructure. Small upfront cost, massive downstream value.

---

## Data Analysis

### Current Output Format (Stage 2: Correction)

Based on analysis of `accidental-president` (447 pages):

**File:** `corrected/page_0051.json`
```json
{
  "page_number": 51,
  "blocks": [
    {
      "block_num": 1,
      "classification": "PAGE_NUMBER",
      "classification_confidence": 1.0,
      "paragraphs": [
        {
          "par_num": 1,
          "text": null,
          "notes": null,
          "confidence": 1.0
        }
      ]
    },
    {
      "block_num": 2,
      "classification": "CHAPTER_HEADING",
      "classification_confidence": 1.0,
      "paragraphs": [
        {
          "par_num": 1,
          "text": null,
          "notes": null,
          "confidence": 1.0
        }
      ]
    },
    {
      "block_num": 3,
      "classification": "BODY",
      "classification_confidence": 1.0,
      "paragraphs": [
        {
          "par_num": 1,
          "text": "Molotov expressed his shock...",
          "notes": "Removed hyphenation at line break",
          "confidence": 1.0
        }
      ]
    }
  ],
  "model_used": "x-ai/grok-2-fast",
  "processing_cost": 0.0021584,
  "timestamp": "2025-10-09T09:50:04.388681",
  "total_blocks": 3,
  "total_corrections": 5
}
```

### Critical Observations

**1. Labels Are Excellent (>95% accuracy)**
- CHAPTER_HEADING reliably marks chapter starts
- TABLE_OF_CONTENTS marks ToC pages (6-7)
- PAGE_NUMBER marks headers/footers with page numbers
- BODY, ENDNOTES, INDEX, BIBLIOGRAPHY properly classified

**2. Corrected Text Is Sparse (~10-20% of paragraphs)**
- When `text: null` → no corrections needed, use OCR text
- When `text: "..."` → LLM made corrections, use this text
- This is why we need to merge with OCR files

**3. OCR Text Still Needed**
- Correction stage only stores corrections, not full text
- Must fetch original OCR text for `text: null` paragraphs

**4. Spatial Metadata Available**
- OCR files contain bounding boxes (bbox)
- Useful for layout analysis (future enhancement)

**5. Block Structure Is Consistent**
- OCR and correction files have identical block/paragraph numbering
- Enables deterministic alignment and merging

### OCR Format (Stage 1)

**File:** `ocr/page_0051.json`
```json
{
  "page_number": 51,
  "page_dimensions": {"width": 1509, "height": 2413},
  "blocks": [
    {
      "block_num": 1,
      "bbox": {"x": 532, "y": 135, "width": 484, "height": 31},
      "paragraphs": [
        {
          "par_num": 1,
          "bbox": {"x": 532, "y": 135, "width": 484, "height": 31},
          "text": "45 / The Accidental President",
          "avg_confidence": 0.928
        }
      ]
    },
    {
      "block_num": 2,
      "bbox": {"x": 300, "y": 200, "width": 900, "height": 50},
      "paragraphs": [
        {
          "par_num": 1,
          "bbox": {"x": 300, "y": 200, "width": 900, "height": 50},
          "text": "Chapter 3: The Cold War Begins",
          "avg_confidence": 0.95
        }
      ]
    },
    {
      "block_num": 3,
      "bbox": {"x": 300, "y": 300, "width": 900, "height": 1500},
      "paragraphs": [
        {
          "par_num": 1,
          "bbox": {"x": 300, "y": 300, "width": 900, "height": 80},
          "text": "Molotov expressed his shock at the sud-\nden reversal of American policy.",
          "avg_confidence": 0.92
        }
      ]
    }
  ]
}
```

---

## Stage 3: Merge & Enrich

### Purpose

Create a single source of truth by merging OCR and correction data into unified page records with full text.

### Input

- `ocr/page_XXXX.json` - Original OCR with bounding boxes and text
- `corrected/page_XXXX.json` - Classifications and corrections

### Output

- `processed/page_XXXX.json` - Merged data with full text

### Output Schema

```python
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum

class BlockType(str, Enum):
    """Semantic block classifications from correction stage."""
    BODY = "BODY"
    CHAPTER_HEADING = "CHAPTER_HEADING"
    SECTION_HEADING = "SECTION_HEADING"
    PAGE_NUMBER = "PAGE_NUMBER"
    HEADER = "HEADER"
    FOOTER = "FOOTER"
    TABLE_OF_CONTENTS = "TABLE_OF_CONTENTS"
    FOOTNOTE = "FOOTNOTE"
    ENDNOTES = "ENDNOTES"
    BIBLIOGRAPHY = "BIBLIOGRAPHY"
    INDEX = "INDEX"
    CAPTION = "CAPTION"
    QUOTE = "QUOTE"

class BoundingBox(BaseModel):
    """Spatial coordinates for block/paragraph."""
    x: int
    y: int
    width: int
    height: int

class ProcessedParagraph(BaseModel):
    """Merged paragraph with full text."""
    par_num: int
    text: str  # Always present (from correction or OCR)
    corrected: bool  # True if LLM corrected this paragraph
    correction_notes: Optional[str]  # Notes from correction stage
    confidence: float  # Confidence score
    bbox: BoundingBox  # Spatial location from OCR

    # Paragraph continuation tracking (cross-page text flow)
    continues_to_next: bool = False  # True if paragraph continues on next page
    continues_from_previous: bool = False  # True if paragraph continues from previous page

class ProcessedBlock(BaseModel):
    """Merged block with classification and full text."""
    block_num: int
    classification: BlockType  # Semantic label from correction
    classification_confidence: float
    paragraphs: List[ProcessedParagraph]
    bbox: BoundingBox  # Block bounding box from OCR

    @property
    def text(self) -> str:
        """Full block text (all paragraphs concatenated)."""
        return "\n\n".join(p.text for p in self.paragraphs)

class ProcessedPage(BaseModel):
    """Complete merged page with all metadata."""
    page_number: int  # PDF page number (1-indexed)
    blocks: List[ProcessedBlock]
    page_dimensions: dict  # Width/height from OCR

    # Source metadata
    ocr_source: str  # Path to OCR file
    correction_source: str  # Path to correction file
    processing_timestamp: str

    # Helper methods
    def get_body_text(self, exclude_headers: bool = True) -> str:
        """
        Get only content text (exclude headers/footers/page numbers).

        Args:
            exclude_headers: If True, filter out HEADER, FOOTER, PAGE_NUMBER

        Returns:
            Concatenated text from BODY, CHAPTER_HEADING, etc.
        """
        exclude_types = {BlockType.HEADER, BlockType.FOOTER, BlockType.PAGE_NUMBER}
        if exclude_headers:
            return "\n\n".join(
                b.text for b in self.blocks
                if b.classification not in exclude_types
            )
        else:
            return "\n\n".join(b.text for b in self.blocks)

    def has_chapter_heading(self) -> bool:
        """Check if page contains a chapter heading."""
        return any(b.classification == BlockType.CHAPTER_HEADING for b in self.blocks)

    def get_chapter_heading_text(self) -> Optional[str]:
        """Extract chapter heading text if present."""
        for block in self.blocks:
            if block.classification == BlockType.CHAPTER_HEADING:
                return block.text
        return None

    def get_page_number_text(self) -> Optional[str]:
        """Extract page number text if present."""
        for block in self.blocks:
            if block.classification == BlockType.PAGE_NUMBER:
                return block.text
        return None

    def has_toc_content(self) -> bool:
        """Check if page contains table of contents."""
        return any(b.classification == BlockType.TABLE_OF_CONTENTS for b in self.blocks)

    def get_toc_text(self) -> str:
        """Extract table of contents text."""
        return "\n\n".join(
            b.text for b in self.blocks
            if b.classification == BlockType.TABLE_OF_CONTENTS
        )
```

### Processing Logic

#### Paragraph Continuation Detection

Before the main merge logic, we need utilities to detect when paragraphs continue across pages:

```python
def detect_paragraph_continuation(text: str) -> bool:
    """
    Detect if a paragraph continues beyond the current page.

    A paragraph continues if:
    - Doesn't end with terminal punctuation (., !, ?, ", ", :, ;)
    - Ends with a hyphen (mid-word hyphenation)
    - Ends mid-sentence (no closing punctuation)

    Args:
        text: Paragraph text to check

    Returns:
        True if paragraph likely continues on next page

    Examples:
        "A simple read of the newspaper gave" → True (no terminal punctuation)
        "The situation was dif-" → True (ends with hyphen)
        "This is complete." → False (terminal punctuation)
    """
    if not text:
        return False

    text = text.rstrip()

    # Check for hyphenation (mid-word split)
    if text.endswith('-'):
        return True

    # Check for terminal punctuation
    terminal_punctuation = {'.', '!', '?', '"', '"', ':', ';'}
    if not text or text[-1] not in terminal_punctuation:
        return True

    return False

def should_join_with_next_page(
    current_page: dict,
    next_page: dict
) -> bool:
    """
    Determine if last paragraph of current page continues on next page.

    Args:
        current_page: Current page OCR/correction data
        next_page: Next page OCR/correction data

    Returns:
        True if pages should be joined
    """
    # Get last block of current page
    if not current_page.get("blocks"):
        return False

    last_block = current_page["blocks"][-1]

    # Only join BODY blocks (don't join headers/footers)
    if last_block.get("classification") != "BODY":
        return False

    # Get last paragraph
    if not last_block.get("paragraphs"):
        return False

    last_para = last_block["paragraphs"][-1]

    # Get paragraph text (from correction or OCR)
    text = last_para.get("text")
    if text is None and "text" in last_para:
        # Fallback to OCR text if available
        text = last_para.get("text")

    if not text:
        return False

    # Check if text continues
    if not detect_paragraph_continuation(text):
        return False

    # Check if next page starts with BODY
    if not next_page.get("blocks"):
        return False

    first_block = next_page["blocks"][0]
    if first_block.get("classification") != "BODY":
        return False

    # Get first paragraph of next page
    if not first_block.get("paragraphs"):
        return False

    first_para = first_block["paragraphs"][0]
    next_text = first_para.get("text", "")

    # Check if next paragraph starts with lowercase (indicates continuation)
    if next_text:
        first_char = next_text.lstrip()[0] if next_text.lstrip() else ""
        if first_char and first_char.islower():
            return True

    return False
```

#### Main Merge Logic

```python
from pathlib import Path
import json
from datetime import datetime

def merge_page(
    ocr_page_path: Path,
    correction_page_path: Path,
    prev_page_data: Optional[dict] = None
) -> ProcessedPage:
    """
    Merge OCR and correction data into unified page.

    Algorithm:
    1. Load both JSON files
    2. Validate block_num alignment (must match exactly)
    3. For each block:
       - Take classification from correction
       - Take bbox from OCR
       - For each paragraph:
         - If correction.text is not None: use correction.text
         - Else: use ocr.text
         - Take bbox from OCR
         - Mark as corrected if correction.text was used
    4. Return ProcessedPage

    Args:
        ocr_page_path: Path to OCR JSON file
        correction_page_path: Path to correction JSON file

    Returns:
        ProcessedPage with merged data

    Raises:
        ValueError: If block/paragraph alignment is invalid
    """
    # Load files
    with open(ocr_page_path) as f:
        ocr_data = json.load(f)
    with open(correction_page_path) as f:
        corr_data = json.load(f)

    # Validate page numbers match
    if ocr_data["page_number"] != corr_data["page_number"]:
        raise ValueError(
            f"Page number mismatch: OCR={ocr_data['page_number']}, "
            f"Correction={corr_data['page_number']}"
        )

    page_num = ocr_data["page_number"]

    # Validate block counts match
    if len(ocr_data["blocks"]) != len(corr_data["blocks"]):
        raise ValueError(
            f"[Page {page_num}] Block count mismatch: "
            f"OCR={len(ocr_data['blocks'])}, Correction={len(corr_data['blocks'])}"
        )

    # Merge blocks
    processed_blocks = []

    for corr_block in corr_data["blocks"]:
        # Find matching OCR block
        ocr_block = next(
            (b for b in ocr_data["blocks"] if b["block_num"] == corr_block["block_num"]),
            None
        )

        if ocr_block is None:
            raise ValueError(
                f"[Page {page_num}] Block {corr_block['block_num']} not found in OCR"
            )

        # Validate paragraph counts match
        if len(ocr_block["paragraphs"]) != len(corr_block["paragraphs"]):
            raise ValueError(
                f"[Page {page_num}, Block {corr_block['block_num']}] "
                f"Paragraph count mismatch: "
                f"OCR={len(ocr_block['paragraphs'])}, Correction={len(corr_block['paragraphs'])}"
            )

        # Merge paragraphs
        processed_paragraphs = []

        for corr_para in corr_block["paragraphs"]:
            # Find matching OCR paragraph
            ocr_para = next(
                (p for p in ocr_block["paragraphs"] if p["par_num"] == corr_para["par_num"]),
                None
            )

            if ocr_para is None:
                raise ValueError(
                    f"[Page {page_num}, Block {corr_block['block_num']}] "
                    f"Paragraph {corr_para['par_num']} not found in OCR"
                )

            # Determine which text to use
            if corr_para["text"] is not None:
                # Correction was made - use corrected text
                text = corr_para["text"]
                corrected = True
            else:
                # No correction - use original OCR text
                text = ocr_para["text"]
                corrected = False

            # Detect paragraph continuation
            continues_to_next = detect_paragraph_continuation(text)

            # Check if this is the first paragraph of first BODY block
            # and if previous page ended with continuation
            continues_from_previous = False
            if (prev_page_data and
                corr_block["block_num"] == 1 and
                corr_para["par_num"] == 1 and
                corr_block["classification"] == "BODY"):
                # Check if prev page's last paragraph continues
                continues_from_previous = should_join_with_next_page(
                    prev_page_data, corr_data
                )

            processed_paragraphs.append(ProcessedParagraph(
                par_num=corr_para["par_num"],
                text=text,
                corrected=corrected,
                correction_notes=corr_para.get("notes"),
                confidence=corr_para["confidence"],
                bbox=BoundingBox(**ocr_para["bbox"]),
                continues_to_next=continues_to_next,
                continues_from_previous=continues_from_previous
            ))

        # Create processed block
        processed_blocks.append(ProcessedBlock(
            block_num=corr_block["block_num"],
            classification=BlockType(corr_block["classification"]),
            classification_confidence=corr_block["classification_confidence"],
            paragraphs=processed_paragraphs,
            bbox=BoundingBox(**ocr_block["bbox"])
        ))

    # Create processed page
    return ProcessedPage(
        page_number=page_num,
        blocks=processed_blocks,
        page_dimensions=ocr_data["page_dimensions"],
        ocr_source=str(ocr_page_path),
        correction_source=str(correction_page_path),
        processing_timestamp=datetime.now().isoformat()
    )
```

### Implementation

**File:** `pipeline/3_merge/__init__.py`

```python
"""
Stage 3: Merge & Enrich

Combines OCR and correction data into unified page records.
"""

from pathlib import Path
from typing import Optional
from infra.checkpoint import CheckpointManager
from infra.logger import PipelineLogger
from .schemas import ProcessedPage, merge_page

def run_merge_stage(
    scan_id: str,
    storage_root: Optional[Path] = None,
    resume: bool = True,
    start_page: int = 1,
    end_page: Optional[int] = None
) -> dict:
    """
    Run Stage 3: Merge OCR and correction data.

    Args:
        scan_id: Book scan identifier
        storage_root: Base directory (default: ~/Documents/book_scans)
        resume: Resume from checkpoint if available
        start_page: First page to process
        end_page: Last page to process (None = all pages)

    Returns:
        Stage metadata (duration, pages processed, etc.)
    """
    # Initialize infrastructure
    storage_root = storage_root or Path.home() / "Documents" / "book_scans"
    book_dir = storage_root / scan_id

    checkpoint = CheckpointManager(
        scan_id=scan_id,
        stage="merge",
        storage_root=storage_root,
        output_dir="processed"
    )

    logger = PipelineLogger(
        scan_id=scan_id,
        stage="merge",
        storage_root=storage_root
    )

    # Get metadata for total pages
    metadata_file = book_dir / "metadata.json"
    with open(metadata_file) as f:
        metadata = json.load(f)
    total_pages = metadata["total_pages_processed"]

    # Get pages to process (respects checkpoint)
    pages_to_process = checkpoint.get_remaining_pages(
        total_pages=total_pages,
        resume=resume,
        start_page=start_page,
        end_page=end_page
    )

    logger.info(f"Starting merge stage", extra={
        "total_pages": total_pages,
        "pages_to_process": len(pages_to_process),
        "resume": resume
    })

    # Create output directory
    output_dir = book_dir / "processed"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Process pages (can be parallelized, but sequential is fast enough)
    errors = []

    for page_num in pages_to_process:
        try:
            # Construct file paths
            ocr_path = book_dir / "ocr" / f"page_{page_num:04d}.json"
            corr_path = book_dir / "corrected" / f"page_{page_num:04d}.json"
            output_path = output_dir / f"page_{page_num:04d}.json"

            # Validate inputs exist
            if not ocr_path.exists():
                raise FileNotFoundError(f"OCR file not found: {ocr_path}")
            if not corr_path.exists():
                raise FileNotFoundError(f"Correction file not found: {corr_path}")

            # Merge page
            processed_page = merge_page(ocr_path, corr_path)

            # Save output
            with open(output_path, 'w') as f:
                f.write(processed_page.model_dump_json(indent=2))

            # Update checkpoint (no cost for this stage)
            checkpoint.mark_completed(page_num, cost_usd=0.0)

            logger.debug(f"Merged page {page_num}")

        except Exception as e:
            logger.error(f"Failed to merge page {page_num}: {e}", extra={
                "page_number": page_num,
                "error": str(e)
            })
            errors.append({"page": page_num, "error": str(e)})

    # Mark stage complete
    stage_metadata = {
        "total_errors": len(errors),
        "errors": errors
    }

    if len(errors) == 0:
        checkpoint.mark_stage_complete(metadata=stage_metadata)
        logger.info("Merge stage completed successfully", extra=stage_metadata)
    else:
        checkpoint.mark_stage_failed(f"{len(errors)} pages failed to merge")
        logger.error("Merge stage completed with errors", extra=stage_metadata)

    return stage_metadata
```

### Checkpointing

- **Granularity:** Per-page (standard pattern)
- **Resume:** Yes - skips already-completed pages
- **Output validation:** Checks that `processed/page_XXXX.json` exists and is valid JSON

### Cost & Performance

- **Cost:** $0 (deterministic merge, no LLM)
- **Time:** ~30s for 400 pages (pure I/O)
- **Parallelization:** Fully parallel (pages are independent)
  - Can process 30 pages concurrently
  - ~400 pages / 30 workers ≈ 14 pages per worker
  - Bottleneck: File I/O (SSD recommended)

### Error Handling

**Validation Errors:**
- Block count mismatch → Log error, skip page, continue
- Paragraph count mismatch → Log error, skip page, continue
- Missing files → Log error, skip page, continue

**Debug Files:**
- Save misaligned pages to `logs/debug/merge_errors/page_XXXX.json`
- Include both OCR and correction data for inspection

**Recovery:**
- Checkpoint ensures failed pages can be retried
- Resume flag skips successfully merged pages

---

## Stage 4: Structure Detection

### Purpose

Extract book structure: page number mapping, table of contents, and chapter boundaries.

### Input

- `processed/page_XXXX.json` - Merged pages with full text and classifications

### Output

- `chapters/page_mapping.json` - PDF ↔ Book page number mapping
- `chapters/toc.json` - Parsed table of contents
- `chapters/chapters.json` - Chapter boundaries and metadata

### Stage 4 Substeps

Stage 4 is divided into three sequential substeps:

1. **4.1: Page Number Mapping** (Deterministic, $0, ~10s)
2. **4.2: Table of Contents Extraction** (Hybrid, $0.05, ~30s)
3. **4.3: Chapter Boundary Detection** (Hybrid, $0.15-0.20, ~2min)

---

### Substep 4.1: Page Number Mapping

**Purpose:** Build bidirectional mapping between PDF pages and book pages.

**Algorithm:**
1. Scan all `processed/page_XXXX.json` files
2. For each page with PAGE_NUMBER classification:
   - Extract page number text from block
   - Detect numbering style (Roman numerals, Arabic numerals, none)
3. Build mapping table
4. Identify front matter, body, and back matter regions

**Output Schema:**

```python
from pydantic import BaseModel
from typing import List, Optional, Literal

class PageMapping(BaseModel):
    """Mapping between PDF page and book page number."""
    pdf_page: int
    book_page: Optional[str]  # "1", "ii", "xii", None (unnumbered)
    page_type: Literal["front_matter", "body", "back_matter"]
    numbering_style: Optional[Literal["roman", "arabic", "none"]]

class BookPageIndex(BaseModel):
    """Complete page numbering index for the book."""
    scan_id: str
    total_pages: int

    # All page mappings
    mappings: List[PageMapping]

    # Quick reference ranges
    front_matter_pages: List[int]  # PDF pages in front matter
    body_pages: tuple[int, int]  # (start_page, end_page) for body
    back_matter_pages: List[int]  # PDF pages in back matter

    # Timestamps
    created_at: str

    def pdf_to_book(self, pdf_page: int) -> Optional[str]:
        """Convert PDF page number to book page number."""
        mapping = next((m for m in self.mappings if m.pdf_page == pdf_page), None)
        return mapping.book_page if mapping else None

    def book_to_pdf(self, book_page: str) -> Optional[int]:
        """Convert book page number to PDF page number."""
        mapping = next((m for m in self.mappings if m.book_page == book_page), None)
        return mapping.pdf_page if mapping else None
```

**Processing Logic:**

```python
import re
from typing import List

def extract_page_number(page_text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract page number and numbering style from page header/footer text.

    Args:
        page_text: Text from PAGE_NUMBER labeled block

    Returns:
        (page_number, numbering_style) or (None, None) if not found

    Examples:
        "45" → ("45", "arabic")
        "xii" → ("xii", "roman")
        "Page 123" → ("123", "arabic")
        "Chapter Title / 45" → ("45", "arabic")
    """
    # Remove common noise
    text = page_text.strip().lower()

    # Roman numeral pattern (i, ii, iii, iv, v, vi, vii, viii, ix, x, xi, xii, ...)
    roman_pattern = r'\b(i{1,3}|iv|vi{0,3}|ix|xi{0,3}|xiv|xv)\b'
    roman_match = re.search(roman_pattern, text)
    if roman_match:
        return (roman_match.group(1), "roman")

    # Arabic numeral pattern (1, 12, 123, ...)
    arabic_pattern = r'\b(\d{1,4})\b'
    arabic_match = re.search(arabic_pattern, text)
    if arabic_match:
        return (arabic_match.group(1), "arabic")

    return (None, None)

def build_page_mapping(pages: List[ProcessedPage]) -> BookPageIndex:
    """
    Build complete page number mapping for the book.

    Algorithm:
    1. Extract page numbers from all pages
    2. Detect transitions:
       - Roman → Arabic: front matter ends, body starts
       - Numbering gaps: potential back matter start
    3. Classify each page as front_matter, body, or back_matter
    4. Return BookPageIndex
    """
    mappings = []

    for page in pages:
        # Try to extract page number
        page_num_text = page.get_page_number_text()

        if page_num_text:
            book_page, numbering_style = extract_page_number(page_num_text)
        else:
            book_page = None
            numbering_style = "none"

        mappings.append({
            "pdf_page": page.page_number,
            "book_page": book_page,
            "numbering_style": numbering_style
        })

    # Detect page type transitions
    for i, mapping in enumerate(mappings):
        if mapping["numbering_style"] == "roman":
            mapping["page_type"] = "front_matter"
        elif mapping["numbering_style"] == "arabic":
            mapping["page_type"] = "body"
        elif mapping["numbering_style"] == "none":
            # Heuristic: first pages = front matter, last pages = back matter
            if i < len(mappings) * 0.1:
                mapping["page_type"] = "front_matter"
            elif i > len(mappings) * 0.9:
                mapping["page_type"] = "back_matter"
            else:
                # Check neighbors
                prev_type = mappings[i-1].get("page_type") if i > 0 else "front_matter"
                mapping["page_type"] = prev_type

    # Build quick reference ranges
    front_matter_pages = [m["pdf_page"] for m in mappings if m["page_type"] == "front_matter"]
    body_pages = [m["pdf_page"] for m in mappings if m["page_type"] == "body"]
    back_matter_pages = [m["pdf_page"] for m in mappings if m["page_type"] == "back_matter"]

    body_range = (min(body_pages), max(body_pages)) if body_pages else (0, 0)

    return BookPageIndex(
        scan_id=pages[0].scan_id,  # Assume consistent scan_id
        total_pages=len(pages),
        mappings=[PageMapping(**m) for m in mappings],
        front_matter_pages=front_matter_pages,
        body_pages=body_range,
        back_matter_pages=back_matter_pages,
        created_at=datetime.now().isoformat()
    )
```

**Output Example:**

`chapters/page_mapping.json`:
```json
{
  "scan_id": "accidental-president",
  "total_pages": 447,
  "mappings": [
    {
      "pdf_page": 1,
      "book_page": null,
      "page_type": "front_matter",
      "numbering_style": "none"
    },
    {
      "pdf_page": 2,
      "book_page": "i",
      "page_type": "front_matter",
      "numbering_style": "roman"
    },
    {
      "pdf_page": 7,
      "book_page": "1",
      "page_type": "body",
      "numbering_style": "arabic"
    },
    {
      "pdf_page": 51,
      "book_page": "45",
      "page_type": "body",
      "numbering_style": "arabic"
    }
  ],
  "front_matter_pages": [1, 2, 3, 4, 5, 6],
  "body_pages": [7, 446],
  "back_matter_pages": [447],
  "created_at": "2025-10-09T10:30:00.000000"
}
```

---

### Substep 4.2: Table of Contents Extraction

**Purpose:** Parse table of contents into structured entries with page references.

**Algorithm:**
1. Find pages with TABLE_OF_CONTENTS classification
2. Extract text from ToC pages
3. Parse ToC entries using regex patterns
4. Use page mapping to convert book pages → PDF pages
5. Optional: LLM validation if parsing confidence is low

**Output Schema:**

```python
from pydantic import BaseModel
from typing import List, Optional, Literal

class ToCEntry(BaseModel):
    """Single table of contents entry."""
    title: str  # Chapter/section title
    level: int  # 0=Part, 1=Chapter, 2=Section
    entry_type: Literal["part_heading", "chapter", "section", "other"]

    # Page references
    book_page: Optional[str]  # Page number from ToC text ("45", "xii")
    pdf_page: Optional[int]  # Looked up via page mapping

    # Metadata
    confidence: float  # Parsing confidence
    raw_text: str  # Original ToC line

class TableOfContents(BaseModel):
    """Complete parsed table of contents."""
    scan_id: str
    toc_pages: List[int]  # PDF pages containing ToC
    entries: List[ToCEntry]

    # Parsing metadata
    parsing_method: Literal["regex", "llm"]
    total_entries: int
    low_confidence_entries: int  # Count of entries with confidence < 0.8

    created_at: str
```

**Processing Logic:**

```python
import re
from typing import List, Optional

def parse_toc_line(line: str) -> Optional[dict]:
    """
    Parse a single ToC line into structured entry.

    Handles common patterns:
    - "Chapter 3: The Cold War Begins ... 45"
    - "Part I"
    - "Timeline ... xii"
    - "April 12, 1945 ... 3"

    Returns:
        dict with title, level, book_page, confidence, or None if not a ToC entry
    """
    line = line.strip()

    # Skip empty lines
    if not line:
        return None

    # Part heading (no page number)
    if line.startswith("Part "):
        return {
            "title": line,
            "level": 0,
            "entry_type": "part_heading",
            "book_page": None,
            "confidence": 0.95,
            "raw_text": line
        }

    # Chapter/section with page number: "Title ... 123"
    # Pattern: capture title, dots, page number
    pattern = r'^(.+?)\s*\.{2,}\s*(\d+|[ivxl]+)$'
    match = re.match(pattern, line, re.IGNORECASE)

    if match:
        title = match.group(1).strip()
        page_num = match.group(2).strip()

        # Detect level by title prefix
        if title.lower().startswith("chapter "):
            level = 1
            entry_type = "chapter"
        elif title.lower().startswith("section "):
            level = 2
            entry_type = "section"
        else:
            level = 1  # Default to chapter
            entry_type = "chapter"

        return {
            "title": title,
            "level": level,
            "entry_type": entry_type,
            "book_page": page_num,
            "confidence": 0.9,
            "raw_text": line
        }

    # Fallback: might be continuation of previous entry or non-entry
    return None

def parse_table_of_contents(
    pages: List[ProcessedPage],
    page_mapping: BookPageIndex
) -> TableOfContents:
    """
    Parse table of contents from labeled pages.

    Args:
        pages: All processed pages
        page_mapping: Page number mapping for book→PDF conversion

    Returns:
        Parsed TableOfContents
    """
    # Find ToC pages
    toc_pages = [p for p in pages if p.has_toc_content()]

    if not toc_pages:
        # No ToC found - return empty
        return TableOfContents(
            scan_id=pages[0].scan_id,
            toc_pages=[],
            entries=[],
            parsing_method="regex",
            total_entries=0,
            low_confidence_entries=0,
            created_at=datetime.now().isoformat()
        )

    # Extract and concatenate ToC text
    toc_text = "\n".join(p.get_toc_text() for p in toc_pages)

    # Parse line by line
    entries = []
    for line in toc_text.split("\n"):
        parsed = parse_toc_line(line)
        if parsed:
            # Look up PDF page via mapping
            if parsed["book_page"]:
                pdf_page = page_mapping.book_to_pdf(parsed["book_page"])
            else:
                pdf_page = None

            entries.append(ToCEntry(
                title=parsed["title"],
                level=parsed["level"],
                entry_type=parsed["entry_type"],
                book_page=parsed["book_page"],
                pdf_page=pdf_page,
                confidence=parsed["confidence"],
                raw_text=parsed["raw_text"]
            ))

    # Count low confidence entries
    low_conf = sum(1 for e in entries if e.confidence < 0.8)

    return TableOfContents(
        scan_id=pages[0].scan_id,
        toc_pages=[p.page_number for p in toc_pages],
        entries=entries,
        parsing_method="regex",
        total_entries=len(entries),
        low_confidence_entries=low_conf,
        created_at=datetime.now().isoformat()
    )
```

**LLM Validation (Optional):**

If `low_confidence_entries / total_entries > 0.3` (>30% uncertain), validate with LLM:

```python
def validate_toc_with_llm(
    toc_text: str,
    llm_client: LLMClient
) -> TableOfContents:
    """
    Use LLM to parse ToC when regex confidence is low.

    Prompt LLM to extract structured ToC entries with confidence scores.
    """
    prompt = f"""
    Parse this table of contents into structured entries.

    Table of Contents:
    {toc_text}

    For each entry, extract:
    - title: Chapter/section title
    - level: 0=Part, 1=Chapter, 2=Section
    - book_page: Page number (if present)

    Return as JSON array of entries.
    """

    response = llm_client.call(
        model="openai/gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"}
    )

    # Parse LLM response and build TableOfContents
    # ... (implementation details)
```

**Cost:** $0.00-0.05 (only if regex parsing fails)

---

### Substep 4.3: Chapter Boundary Detection

**Purpose:** Detect chapter boundaries using labels, validate against ToC, and confirm with LLM.

**Algorithm:**
1. Scan for CHAPTER_HEADING classifications
2. Extract chapter titles and page numbers
3. Cross-validate against ToC
4. LLM validates ALL boundaries (liberal strategy)
5. Build final chapter structure

**Output Schema:**

```python
from pydantic import BaseModel
from typing import List, Optional, Literal

class ChapterBoundary(BaseModel):
    """A single chapter in the book."""
    chapter_num: int  # 1-indexed
    title: str  # Chapter title

    # Page references
    start_page: int  # PDF page where chapter starts
    end_page: int  # PDF page where chapter ends
    start_book_page: Optional[str]  # Book page number (e.g., "45")
    end_book_page: Optional[str]

    # Detection metadata
    detected_by: Literal["HEADING_LABEL", "TOC_ENTRY", "LLM_VALIDATION"]
    confidence: float  # 0.0-1.0

    # ToC cross-reference
    toc_match: bool  # True if ToC entry matches this chapter
    toc_page_expected: Optional[int]  # Expected PDF page from ToC
    toc_page_delta: Optional[int]  # Difference between detected and ToC (pages)

    # Content stats
    page_count: int
    word_count: Optional[int]

class BookStructure(BaseModel):
    """Complete book structure with all chapters."""
    scan_id: str
    total_pages: int

    # Main content
    chapters: List[ChapterBoundary]
    total_chapters: int

    # Front/back matter
    front_matter_pages: List[int]
    back_matter_pages: List[int]

    # Detection metadata
    detection_method: str  # Description of detection approach
    toc_available: bool
    llm_validation_used: bool
    validation_cost: float  # Total LLM cost

    # Quality metrics
    avg_chapter_confidence: float
    low_confidence_chapters: int  # Count < 0.85
    toc_mismatch_count: int

    created_at: str
```

**Processing Logic:**

```python
def detect_chapters(
    pages: List[ProcessedPage],
    page_mapping: BookPageIndex,
    toc: TableOfContents,
    llm_client: LLMClient
) -> BookStructure:
    """
    Detect chapter boundaries using labels + ToC + LLM validation.

    Algorithm:
    1. Scan for CHAPTER_HEADING labels
    2. Cross-validate against ToC
    3. LLM validates ALL boundaries (liberal strategy)
    """
    # Step 1: Detect headings from labels
    detected_chapters = []
    chapter_num = 1

    for page in pages:
        if page.has_chapter_heading():
            title = page.get_chapter_heading_text()
            book_page = page_mapping.pdf_to_book(page.page_number)

            detected_chapters.append({
                "chapter_num": chapter_num,
                "title": title,
                "start_page": page.page_number,
                "start_book_page": book_page,
                "detected_by": "HEADING_LABEL",
                "confidence": 0.9  # High confidence from label
            })
            chapter_num += 1

    # Step 2: Cross-validate with ToC
    if toc.entries:
        for chapter in detected_chapters:
            # Find matching ToC entry
            toc_entry = next(
                (e for e in toc.entries
                 if titles_similar(chapter["title"], e.title)),
                None
            )

            if toc_entry and toc_entry.pdf_page:
                chapter["toc_match"] = True
                chapter["toc_page_expected"] = toc_entry.pdf_page
                chapter["toc_page_delta"] = chapter["start_page"] - toc_entry.pdf_page

                # Adjust confidence based on match quality
                if abs(chapter["toc_page_delta"]) <= 1:
                    chapter["confidence"] = min(1.0, chapter["confidence"] + 0.05)
                elif abs(chapter["toc_page_delta"]) > 3:
                    chapter["confidence"] *= 0.85  # Reduce confidence
            else:
                chapter["toc_match"] = False

    # Step 3: LLM validation for ALL chapters (liberal strategy)
    validation_cost = 0.0

    for chapter in detected_chapters:
        # Get context around chapter boundary (3 pages before/after)
        context_pages = get_page_range(
            pages,
            chapter["start_page"] - 3,
            chapter["start_page"] + 3
        )

        # Build context text
        context_text = "\n\n---PAGE BREAK---\n\n".join(
            f"[Page {p.page_number}]\n{p.get_body_text()}"
            for p in context_pages
        )

        # LLM validation prompt
        prompt = f"""
        I detected a chapter boundary with the following information:

        - Detected page: {chapter["start_page"]}
        - Detected title: "{chapter["title"]}"
        - ToC match: {chapter.get("toc_match", False)}
        - ToC expected page: {chapter.get("toc_page_expected", "N/A")}

        Context (3 pages before/after):
        {context_text}

        Please validate:
        1. Is page {chapter["start_page"]} the correct chapter start?
        2. Is the title "{chapter["title"]}" accurate?
        3. If not, what are the correct page and title?
        4. Your confidence (0.0-1.0)

        Respond in JSON format:
        {{
          "is_correct": bool,
          "correct_page": int,
          "correct_title": str,
          "confidence": float,
          "reasoning": str
        }}
        """

        # Call LLM
        response = llm_client.call(
            model="openai/gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"}
        )

        validation_cost += response["cost_usd"]
        result = response["parsed_response"]

        # Update chapter based on LLM feedback
        if result["is_correct"]:
            chapter["confidence"] = result["confidence"]
            chapter["detected_by"] = "LLM_VALIDATION"
        else:
            # LLM suggests correction
            chapter["start_page"] = result["correct_page"]
            chapter["title"] = result["correct_title"]
            chapter["confidence"] = result["confidence"]
            chapter["detected_by"] = "LLM_VALIDATION"

    # Fill in end_page for each chapter
    for i, chapter in enumerate(detected_chapters):
        if i < len(detected_chapters) - 1:
            chapter["end_page"] = detected_chapters[i + 1]["start_page"] - 1
        else:
            chapter["end_page"] = pages[-1].page_number

        chapter["page_count"] = chapter["end_page"] - chapter["start_page"] + 1
        chapter["end_book_page"] = page_mapping.pdf_to_book(chapter["end_page"])

    # Build BookStructure
    chapters = [ChapterBoundary(**c) for c in detected_chapters]

    # Calculate metrics
    avg_conf = sum(c.confidence for c in chapters) / len(chapters) if chapters else 0
    low_conf = sum(1 for c in chapters if c.confidence < 0.85)
    toc_mismatches = sum(1 for c in chapters if c.toc_match and abs(c.toc_page_delta) > 3)

    return BookStructure(
        scan_id=pages[0].scan_id,
        total_pages=len(pages),
        chapters=chapters,
        total_chapters=len(chapters),
        front_matter_pages=page_mapping.front_matter_pages,
        back_matter_pages=page_mapping.back_matter_pages,
        detection_method="HEADING_LABEL + TOC + LLM_VALIDATION",
        toc_available=(len(toc.entries) > 0),
        llm_validation_used=True,
        validation_cost=validation_cost,
        avg_chapter_confidence=avg_conf,
        low_confidence_chapters=low_conf,
        toc_mismatch_count=toc_mismatches,
        created_at=datetime.now().isoformat()
    )

def titles_similar(title1: str, title2: str, threshold: float = 0.8) -> bool:
    """
    Check if two chapter titles are similar.

    Uses simple fuzzy matching (can be enhanced with Levenshtein distance).
    """
    # Normalize titles
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()

    # Remove common prefixes
    t1 = t1.replace("chapter ", "").replace("section ", "")
    t2 = t2.replace("chapter ", "").replace("section ", "")

    # Exact match
    if t1 == t2:
        return True

    # Substring match
    if t1 in t2 or t2 in t1:
        return True

    # Could add Levenshtein distance here for more sophisticated matching
    return False
```

**Cost:** $0.15-0.20 per book (validating 15-20 chapters at ~$0.01 each)

---

### Stage 4 Implementation

**File:** `pipeline/4_structure/__init__.py`

```python
"""
Stage 4: Structure Detection

Extracts book structure: page mapping, ToC, and chapter boundaries.
"""

from pathlib import Path
from typing import Optional
from infra.checkpoint import CheckpointManager
from infra.logger import PipelineLogger
from infra.llm_client import LLMClient
from .schemas import BookPageIndex, TableOfContents, BookStructure
from .page_mapping import build_page_mapping
from .toc_parser import parse_table_of_contents
from .chapter_detection import detect_chapters

def run_structure_stage(
    scan_id: str,
    storage_root: Optional[Path] = None,
    skip_llm_validation: bool = False
) -> dict:
    """
    Run Stage 4: Structure Detection.

    Substeps:
    1. Build page number mapping (PDF ↔ book pages)
    2. Parse table of contents
    3. Detect chapter boundaries with LLM validation

    Args:
        scan_id: Book scan identifier
        storage_root: Base directory (default: ~/Documents/book_scans)
        skip_llm_validation: Skip LLM validation (save cost, reduce accuracy)

    Returns:
        Stage metadata
    """
    # Initialize infrastructure
    storage_root = storage_root or Path.home() / "Documents" / "book_scans"
    book_dir = storage_root / scan_id

    logger = PipelineLogger(
        scan_id=scan_id,
        stage="structure",
        storage_root=storage_root
    )

    llm_client = LLMClient(
        logger=logger,
        default_model="openai/gpt-4o-mini"
    )

    logger.info("Starting structure detection stage")

    # Load all processed pages
    processed_dir = book_dir / "processed"
    pages = load_all_pages(processed_dir)

    logger.info(f"Loaded {len(pages)} processed pages")

    # Create output directory
    chapters_dir = book_dir / "chapters"
    chapters_dir.mkdir(parents=True, exist_ok=True)

    # Substep 1: Page mapping
    logger.info("Building page number mapping...")
    page_mapping = build_page_mapping(pages)

    with open(chapters_dir / "page_mapping.json", "w") as f:
        f.write(page_mapping.model_dump_json(indent=2))

    logger.info(f"Page mapping complete: {len(page_mapping.mappings)} pages mapped")

    # Substep 2: ToC parsing
    logger.info("Parsing table of contents...")
    toc = parse_table_of_contents(pages, page_mapping)

    with open(chapters_dir / "toc.json", "w") as f:
        f.write(toc.model_dump_json(indent=2))

    logger.info(f"ToC parsing complete: {toc.total_entries} entries found")

    # Substep 3: Chapter detection
    logger.info("Detecting chapter boundaries...")
    book_structure = detect_chapters(
        pages,
        page_mapping,
        toc,
        llm_client,
        skip_llm_validation=skip_llm_validation
    )

    with open(chapters_dir / "chapters.json", "w") as f:
        f.write(book_structure.model_dump_json(indent=2))

    logger.info(f"Chapter detection complete: {book_structure.total_chapters} chapters detected")
    logger.info(f"LLM validation cost: ${book_structure.validation_cost:.4f}")

    # Build metadata
    metadata = {
        "total_chapters": book_structure.total_chapters,
        "toc_entries": toc.total_entries,
        "validation_cost": book_structure.validation_cost,
        "avg_confidence": book_structure.avg_chapter_confidence
    }

    logger.info("Structure detection stage complete", extra=metadata)

    return metadata
```

### Checkpointing

- **Granularity:** Single-stage checkpoint (all 3 substeps run together)
- **Resume:** If stage fails, entire stage reruns (fast enough at ~3min)
- **Rationale:** Substeps are interdependent, not worth fine-grained checkpointing

### Cost & Performance

- **Cost:** $0.20-0.25 per book
  - Substep 4.1: $0.00
  - Substep 4.2: $0.00-0.05
  - Substep 4.3: $0.15-0.20
- **Time:** ~2-3 minutes
  - Substep 4.1: ~10s
  - Substep 4.2: ~30s
  - Substep 4.3: ~2min (LLM latency)
- **Parallelization:** Sequential (substeps depend on each other)

---

## Stage 5: Chunk Assembly

### Purpose

Split book into ~5-page semantic chunks for RAG queries and audiobook generation.

### Input

- `processed/page_XXXX.json` - Full processed pages
- `chapters/chapters.json` - Chapter boundaries

### Output

- `chunks/manifest.json` - Index of all chunks + references to front/back matter
- `chunks/chunk_XXXX.json` - Individual chunk files (body content only)
- `chunks/front_matter.json` - Front matter artifact (title, copyright, ToC, preface)
- `chunks/back_matter.json` - Back matter artifacts (endnotes, bibliography, index)

### Output Schema

```python
from pydantic import BaseModel
from typing import List, Optional, Dict

class FrontMatter(BaseModel):
    """Front matter content (title page, copyright, ToC, preface, etc.)."""
    pages: List[int]  # PDF pages
    sections: Dict[str, str]  # Section name → text
    # e.g., {"title_page": "...", "copyright": "...", "table_of_contents": "...", "preface": "..."}
    word_count: int
    created_at: str

class BackMatterSection(BaseModel):
    """A single back matter section (endnotes, bibliography, index)."""
    section_type: Literal["ENDNOTES", "BIBLIOGRAPHY", "INDEX", "OTHER"]
    title: str
    pages: List[int]  # PDF pages
    text: str  # Full text of section
    word_count: int

class BackMatter(BaseModel):
    """Back matter content (endnotes, bibliography, index, etc.)."""
    sections: List[BackMatterSection]
    total_pages: int
    created_at: str

class Chunk(BaseModel):
    """A ~5-page semantic chunk of book BODY content."""
    chunk_id: int  # 1-indexed

    # Page range
    start_page: int  # PDF page
    end_page: int  # PDF page
    page_count: int

    # Book page references (for user-facing display)
    start_book_page: Optional[str]  # e.g., "45"
    end_book_page: Optional[str]  # e.g., "49"

    # Chapter context
    chapter_num: int
    chapter_title: str

    # Content
    text: str  # Full text from all pages in chunk
    word_count: int

    # Chunk relationships
    is_chapter_start: bool  # True if chunk contains chapter boundary
    prev_chunk_id: Optional[int]
    next_chunk_id: Optional[int]

    # Metadata
    created_at: str

class ChunkManifest(BaseModel):
    """Index of all chunks and special sections in the book."""
    scan_id: str

    # Body content (chunked)
    total_chunks: int
    chunks: List[Chunk]

    # Front matter (not chunked - single artifact)
    front_matter: Optional[FrontMatter]

    # Back matter (not chunked - separate artifacts per section)
    back_matter: Optional[BackMatter]

    # Chunking configuration
    pages_per_chunk: int  # Target (default: 5)
    strategy: Literal["chapter_aware_fixed"]

    # Statistics
    avg_chunk_size: int  # Average word count
    min_chunk_size: int
    max_chunk_size: int

    created_at: str

    def get_chunk(self, chunk_id: int) -> Optional[Chunk]:
        """Get chunk by ID."""
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    def get_chunks_for_chapter(self, chapter_num: int) -> List[Chunk]:
        """Get all chunks in a chapter."""
        return [c for c in self.chunks if c.chapter_num == chapter_num]

    def get_chunk_for_page(self, page_num: int) -> Optional[Chunk]:
        """Find chunk containing a specific page."""
        return next(
            (c for c in self.chunks if c.start_page <= page_num <= c.end_page),
            None
        )
```

### Processing Logic

#### Paragraph Continuation Joining

When assembling chunk text, we need to properly join paragraphs that continue across pages:

```python
def join_pages_with_continuations(pages: List[ProcessedPage]) -> str:
    """
    Join text from multiple pages, handling paragraph continuations.

    When a paragraph ends with continues_to_next=True and the next page
    starts with continues_from_previous=True, join them without page break.

    Args:
        pages: List of processed pages to join

    Returns:
        Joined text with proper paragraph continuations

    Example:
        Page 1 ends: "A simple read of the newspaper gave" (continues_to_next=True)
        Page 2 starts: "him insight into..." (continues_from_previous=True)
        Result: "A simple read of the newspaper gave him insight into..."
    """
    if not pages:
        return ""

    text_segments = []

    for i, page in enumerate(pages):
        page_text = page.get_body_text(exclude_headers=True)

        # Check if previous page ended with continuation
        should_join = False
        if i > 0:
            prev_page = pages[i - 1]
            # Check if prev page's last BODY block has continues_to_next=True
            for block in reversed(prev_page.blocks):
                if block.classification == BlockType.BODY and block.paragraphs:
                    last_para = block.paragraphs[-1]
                    if last_para.continues_to_next:
                        # And check if current page first BODY block has continues_from_previous=True
                        for curr_block in page.blocks:
                            if curr_block.classification == BlockType.BODY and curr_block.paragraphs:
                                first_para = curr_block.paragraphs[0]
                                if first_para.continues_from_previous:
                                    should_join = True
                                break
                    break

        if should_join:
            # Join without page break (just a space)
            text_segments.append(page_text)
        else:
            # Add page break marker
            if text_segments:
                text_segments.append("\n\n---PAGE BREAK---\n\n")
            text_segments.append(page_text)

    return "".join(text_segments)
```

#### Front/Back Matter Extraction

```python
def extract_front_matter(
    pages: List[ProcessedPage],
    book_structure: BookStructure
) -> Optional[FrontMatter]:
    """
    Extract front matter as single artifact (not chunked).

    Front matter includes: title page, copyright, ToC, preface, etc.
    """
    front_matter_pages = [
        p for p in pages
        if p.page_number in book_structure.front_matter_pages
    ]

    if not front_matter_pages:
        return None

    # Group by section type (heuristic based on classification)
    sections = {}
    for page in front_matter_pages:
        for block in page.blocks:
            if block.classification == BlockType.TABLE_OF_CONTENTS:
                sections["table_of_contents"] = sections.get("table_of_contents", "") + block.text + "\n\n"
            elif block.classification in [BlockType.BODY, BlockType.SECTION_HEADING]:
                # Assume it's preface or introduction
                sections["preface"] = sections.get("preface", "") + block.text + "\n\n"
            # Could add more section detection here

    # Fallback: combine all text if no specific sections detected
    if not sections:
        all_text = "\n\n---PAGE BREAK---\n\n".join(p.get_body_text(exclude_headers=True) for p in front_matter_pages)
        sections["front_matter"] = all_text

    word_count = sum(len(text.split()) for text in sections.values())

    return FrontMatter(
        pages=[p.page_number for p in front_matter_pages],
        sections=sections,
        word_count=word_count,
        created_at=datetime.now().isoformat()
    )

def extract_back_matter(
    pages: List[ProcessedPage],
    book_structure: BookStructure
) -> Optional[BackMatter]:
    """
    Extract back matter as separate section artifacts (not chunked).

    Back matter includes: endnotes, bibliography, index, etc.
    """
    back_matter_pages = [
        p for p in pages
        if p.page_number in book_structure.back_matter_pages
    ]

    if not back_matter_pages:
        return None

    # Group pages by classification
    sections = []
    current_section = None
    current_pages = []
    current_text = []

    for page in back_matter_pages:
        # Determine dominant classification for this page
        page_classifications = [b.classification for b in page.blocks if b.classification in [BlockType.ENDNOTES, BlockType.BIBLIOGRAPHY, BlockType.INDEX]]

        if not page_classifications:
            # No special classification - include in current section or skip
            if current_section:
                current_pages.append(page.page_number)
                current_text.append(page.get_body_text(exclude_headers=True))
            continue

        # Get dominant classification
        page_section_type = max(set(page_classifications), key=page_classifications.count)

        if page_section_type != current_section:
            # Save previous section
            if current_section:
                sections.append(BackMatterSection(
                    section_type=current_section,
                    title=current_section.title(),  # e.g., "Endnotes", "Bibliography"
                    pages=current_pages,
                    text="\n\n---PAGE BREAK---\n\n".join(current_text),
                    word_count=len(" ".join(current_text).split())
                ))

            # Start new section
            current_section = page_section_type
            current_pages = [page.page_number]
            current_text = [page.get_body_text(exclude_headers=True)]
        else:
            # Continue current section
            current_pages.append(page.page_number)
            current_text.append(page.get_body_text(exclude_headers=True))

    # Save final section
    if current_section:
        sections.append(BackMatterSection(
            section_type=current_section,
            title=current_section.title(),
            pages=current_pages,
            text="\n\n---PAGE BREAK---\n\n".join(current_text),
            word_count=len(" ".join(current_text).split())
        ))

    if not sections:
        return None

    return BackMatter(
        sections=sections,
        total_pages=len(back_matter_pages),
        created_at=datetime.now().isoformat()
    )
```

#### Chunk Creation Logic (Body Content Only)

```python
def create_chunks(
    pages: List[ProcessedPage],
    book_structure: BookStructure,
    page_mapping: BookPageIndex,
    pages_per_chunk: int = 5
) -> ChunkManifest:
    """
    Create chapter-aware fixed-size chunks for BODY content only.

    Front matter and back matter are extracted as separate artifacts (not chunked).

    Strategy:
    1. Extract front matter (single artifact)
    2. Extract back matter sections (separate artifacts)
    3. Process chapters sequentially (body content)
    4. Split each chapter into N-page chunks
    5. NEVER split chunks across chapter boundaries
    6. Last chunk of chapter may be < N pages

    Args:
        pages: All processed pages
        book_structure: Chapter boundaries
        page_mapping: Page number mapping
        pages_per_chunk: Target pages per chunk (default: 5)

    Returns:
        ChunkManifest with body chunks + front/back matter artifacts
    """
    # Extract front matter (not chunked)
    front_matter = extract_front_matter(pages, book_structure)

    # Extract back matter (not chunked)
    back_matter = extract_back_matter(pages, book_structure)

    # Chunk body content (chapters)
    chunks = []
    chunk_id = 1

    for chapter in book_structure.chapters:
        # Get pages for this chapter
        chapter_pages = [
            p for p in pages
            if chapter.start_page <= p.page_number <= chapter.end_page
        ]

        # Split into chunks
        for i in range(0, len(chapter_pages), pages_per_chunk):
            chunk_pages = chapter_pages[i:i + pages_per_chunk]

            # Combine text from all pages in chunk, handling paragraph continuations
            chunk_text = join_pages_with_continuations(chunk_pages)

            # Get book page numbers
            start_book_page = page_mapping.pdf_to_book(chunk_pages[0].page_number)
            end_book_page = page_mapping.pdf_to_book(chunk_pages[-1].page_number)

            chunks.append(Chunk(
                chunk_id=chunk_id,
                start_page=chunk_pages[0].page_number,
                end_page=chunk_pages[-1].page_number,
                page_count=len(chunk_pages),
                start_book_page=start_book_page,
                end_book_page=end_book_page,
                chapter_num=chapter.chapter_num,
                chapter_title=chapter.title,
                text=chunk_text,
                word_count=len(chunk_text.split()),
                is_chapter_start=(i == 0),
                prev_chunk_id=(chunk_id - 1) if chunk_id > 1 else None,
                next_chunk_id=(chunk_id + 1),  # Will fix for last chunk
                created_at=datetime.now().isoformat()
            ))

            chunk_id += 1

    # Fix next_chunk_id for last chunk
    if chunks:
        chunks[-1].next_chunk_id = None

    # Calculate statistics
    word_counts = [c.word_count for c in chunks]

    return ChunkManifest(
        scan_id=pages[0].scan_id,
        total_chunks=len(chunks),
        chunks=chunks,
        front_matter=front_matter,  # Single artifact (not chunked)
        back_matter=back_matter,  # Separate section artifacts (not chunked)
        pages_per_chunk=pages_per_chunk,
        strategy="chapter_aware_fixed",
        avg_chunk_size=sum(word_counts) // len(word_counts) if word_counts else 0,
        min_chunk_size=min(word_counts) if word_counts else 0,
        max_chunk_size=max(word_counts) if word_counts else 0,
        created_at=datetime.now().isoformat()
    )
```

### Implementation

**File:** `pipeline/5_chunks/__init__.py`

```python
"""
Stage 5: Chunk Assembly

Creates semantic chunks for RAG and audiobook generation.
"""

from pathlib import Path
from typing import Optional
from infra.logger import PipelineLogger
from .schemas import ChunkManifest, create_chunks

def run_chunk_stage(
    scan_id: str,
    storage_root: Optional[Path] = None,
    pages_per_chunk: int = 5
) -> dict:
    """
    Run Stage 5: Chunk Assembly.

    Args:
        scan_id: Book scan identifier
        storage_root: Base directory (default: ~/Documents/book_scans)
        pages_per_chunk: Target pages per chunk (default: 5)

    Returns:
        Stage metadata
    """
    # Initialize infrastructure
    storage_root = storage_root or Path.home() / "Documents" / "book_scans"
    book_dir = storage_root / scan_id

    logger = PipelineLogger(
        scan_id=scan_id,
        stage="chunks",
        storage_root=storage_root
    )

    logger.info("Starting chunk assembly stage")

    # Load inputs
    pages = load_all_pages(book_dir / "processed")
    book_structure = load_book_structure(book_dir / "chapters" / "chapters.json")
    page_mapping = load_page_mapping(book_dir / "chapters" / "page_mapping.json")

    logger.info(f"Loaded {len(pages)} pages, {book_structure.total_chapters} chapters")

    # Create chunks
    manifest = create_chunks(pages, book_structure, page_mapping, pages_per_chunk)

    logger.info(f"Created {manifest.total_chunks} chunks")

    # Create output directory
    chunks_dir = book_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Save individual chunk files (body content)
    for chunk in manifest.chunks:
        chunk_file = chunks_dir / f"chunk_{chunk.chunk_id:04d}.json"
        with open(chunk_file, "w") as f:
            f.write(chunk.model_dump_json(indent=2))

    # Save front matter artifact (if present)
    if manifest.front_matter:
        front_matter_file = chunks_dir / "front_matter.json"
        with open(front_matter_file, "w") as f:
            f.write(manifest.front_matter.model_dump_json(indent=2))

    # Save back matter artifacts (if present)
    if manifest.back_matter:
        back_matter_file = chunks_dir / "back_matter.json"
        with open(back_matter_file, "w") as f:
            f.write(manifest.back_matter.model_dump_json(indent=2))

    # Save manifest (includes references to front/back matter)
    manifest_file = chunks_dir / "manifest.json"
    with open(manifest_file, "w") as f:
        f.write(manifest.model_dump_json(indent=2))

    logger.info("Chunk assembly complete", extra={
        "total_chunks": manifest.total_chunks,
        "avg_chunk_size": manifest.avg_chunk_size
    })

    return {
        "total_chunks": manifest.total_chunks,
        "avg_chunk_size": manifest.avg_chunk_size
    }
```

### Checkpointing

- **Not needed** - Fast deterministic process (<10s for 400 pages)
- If process crashes, simply re-run (minimal cost)

### Cost & Performance

- **Cost:** $0.00 (deterministic, no LLM)
- **Time:** ~10-30s for 400 pages
- **Parallelization:** Could parallelize chunk generation, but sequential is fast enough

---

## Data Flow

### Visual Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────┐
│ EXISTING STAGES (Stages 0-2: Complete)                          │
├─────────────────────────────────────────────────────────────────┤
│ Stage 0: Ingest     → source/*.pdf + metadata.json              │
│ Stage 1: OCR        → ocr/page_XXXX.json (blocks, text, bbox)  │
│ Stage 2: Correction → corrected/page_XXXX.json (labels, fixes) │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ NEW STAGE 3: Merge & Enrich                                     │
│ Cost: $0  |  Time: 30s  |  Parallelizable: Yes                 │
├─────────────────────────────────────────────────────────────────┤
│ Input:  ocr/*.json + corrected/*.json                           │
│ Logic:  Deterministic merge (corrected text + OCR fallback)     │
│ Output: processed/page_XXXX.json (full text + all metadata)    │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ NEW STAGE 4: Structure Detection                                │
│ Cost: $0.20-0.25  |  Time: 2-3min  |  Parallelizable: No       │
├─────────────────────────────────────────────────────────────────┤
│ Substep 4.1: Page Number Mapping (Deterministic, $0, 10s)      │
│   Input:  processed/*.json                                      │
│   Logic:  Extract PAGE_NUMBER labels, detect transitions        │
│   Output: chapters/page_mapping.json                            │
│                                                                  │
│ Substep 4.2: ToC Extraction (Hybrid, $0-0.05, 30s)             │
│   Input:  processed/*.json + page_mapping.json                  │
│   Logic:  Parse TABLE_OF_CONTENTS, map book→PDF pages           │
│   Output: chapters/toc.json                                     │
│                                                                  │
│ Substep 4.3: Chapter Detection (Hybrid, $0.15-0.20, 2min)      │
│   Input:  processed/*.json + toc.json + page_mapping.json       │
│   Logic:  Scan CHAPTER_HEADING labels, cross-validate ToC,      │
│           LLM validates ALL boundaries (liberal strategy)       │
│   Output: chapters/chapters.json                                │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ NEW STAGE 5: Chunk Assembly                                     │
│ Cost: $0  |  Time: 10-30s  |  Parallelizable: Yes              │
├─────────────────────────────────────────────────────────────────┤
│ Input:  processed/*.json + chapters/chapters.json +             │
│         chapters/page_mapping.json                              │
│ Logic:  Split into ~5-page chunks, never cross chapters         │
│ Output: chunks/manifest.json + chunks/chunk_XXXX.json          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ APPLICATIONS                                                     │
├─────────────────────────────────────────────────────────────────┤
│ MCP Server:  chunks/manifest.json → RAG queries, chapter nav    │
│ Audiobook:   chunks/*.json → TTS pipeline with chapter markers  │
│ Book Reader: chapters/chapters.json → navigation, citations     │
└─────────────────────────────────────────────────────────────────┘
```

### Directory Structure (After All Stages)

```
~/Documents/book_scans/
└── accidental-president/
    ├── source/
    │   └── book.pdf                    # Original PDF
    ├── metadata.json                    # Book metadata from ingest
    ├── ocr/
    │   └── page_XXXX.json              # OCR output (blocks, text, bbox)
    ├── corrected/
    │   └── page_XXXX.json              # Corrections + labels
    ├── processed/                       # NEW: Stage 3 output
    │   └── page_XXXX.json              # Merged full text + all metadata
    ├── chapters/                        # NEW: Stage 4 output
    │   ├── page_mapping.json           # PDF ↔ Book page mapping
    │   ├── toc.json                    # Parsed table of contents
    │   └── chapters.json               # Chapter boundaries
    ├── chunks/                          # NEW: Stage 5 output
    │   ├── manifest.json               # Index of all chunks + front/back matter refs
    │   ├── chunk_XXXX.json             # Individual chunks (body content)
    │   ├── front_matter.json           # Front matter artifact (not chunked)
    │   └── back_matter.json            # Back matter artifacts (not chunked)
    ├── checkpoints/
    │   ├── ocr.json
    │   ├── correction.json
    │   ├── merge.json                  # NEW
    │   ├── structure.json              # NEW
    │   └── chunks.json                 # NEW
    └── logs/
        ├── ocr_TIMESTAMP.jsonl
        ├── correction_TIMESTAMP.jsonl
        ├── merge_TIMESTAMP.jsonl       # NEW
        ├── structure_TIMESTAMP.jsonl   # NEW
        └── chunks_TIMESTAMP.jsonl      # NEW
```

---

## Cost & Performance

### Per-Book Cost Breakdown (400-page book)

| Stage | Operation | Cost | Notes |
|-------|-----------|------|-------|
| **Stage 3: Merge** | Deterministic I/O | $0.00 | Pure file operations |
| **Stage 4.1: Page Mapping** | Deterministic scan | $0.00 | Extract labels |
| **Stage 4.2: ToC Parse** | Regex + optional LLM | $0.00-0.05 | LLM only if needed |
| **Stage 4.3: Chapters** | LLM validation (liberal) | $0.15-0.20 | Validate all boundaries |
| **Stage 5: Chunks** | Deterministic assembly | $0.00 | Split + format |
| **Total (Stages 3-5)** | | **$0.20-0.25** | |

**Comparison:**
- Old design (removed): $2-5 per book
- New design: $0.20-0.25 per book
- **Savings: 10-20x cheaper**

### Time Breakdown (400-page book)

| Stage | Time | Bottleneck |
|-------|------|------------|
| Stage 3: Merge | 30s | File I/O |
| Stage 4: Structure | 2-3min | LLM latency (substep 4.3) |
| Stage 5: Chunks | 10-30s | File writes |
| **Total** | **3-4min** | |

### Scaling

**Small book (100 pages):**
- Cost: ~$0.05 (fewer chapters to validate)
- Time: ~1min

**Large book (800 pages):**
- Cost: ~$0.40 (more chapters to validate)
- Time: ~6-8min

**Cost scales linearly** with page count (dominated by chapter validation).

### Performance Optimization Opportunities

1. **Parallel merge (Stage 3):** Process 30 pages concurrently → 10s for 400 pages
2. **Batch LLM validation:** Validate 5 boundaries per call → 50% latency reduction
3. **Cache ToC patterns:** Reuse parsers for same publisher → Skip LLM validation
4. **SSD storage:** Faster file I/O → 50% time reduction for stages 3 & 5

---

## Implementation Roadmap

### Week 1: Stage 3 Implementation
**Goal:** Merge OCR + corrected data

**Tasks:**
1. Create `pipeline/3_merge/` directory structure
2. Define `ProcessedPage` schema in `schemas.py`
3. Implement `merge_page()` logic in `__init__.py`
4. Add standard infrastructure (checkpoint, logging, error handling)
5. Write unit tests for merge logic
6. Test on `accidental-president` (validate all 447 pages merge cleanly)
7. Add CLI command: `uv run python ar.py merge <scan_id>`

**Acceptance Criteria:**
- ✅ All 447 pages merge without errors
- ✅ Spot-check 10 random pages: corrected text used when available, OCR fallback works
- ✅ Checkpoint resume works (kill mid-process, resume completes)
- ✅ Cost tracking shows $0.00
- ✅ Tests pass (`pytest tests/pipeline/test_merge.py`)

**Estimated Time:** 2-3 days

---

### Week 2: Stage 4 Implementation
**Goal:** Detect chapter boundaries with page mapping

**Tasks:**

**Substep 4.1: Page Mapping**
1. Implement `build_page_mapping()` in `page_mapping.py`
2. Write tests for page number extraction
3. Validate on `accidental-president` (check Roman→Arabic transition)

**Substep 4.2: ToC Parsing**
4. Implement `parse_table_of_contents()` in `toc_parser.py`
5. Write regex patterns for common ToC formats
6. Add optional LLM validation for low-confidence parsing
7. Validate on `accidental-president` (check pages 6-7)

**Substep 4.3: Chapter Detection**
8. Implement `detect_chapters()` in `chapter_detection.py`
9. Add LLM validation for ALL boundaries
10. Add cross-validation logic (ToC vs. detected)
11. Write unit tests
12. Test on `accidental-president` (validate against known structure)
13. Add CLI command: `uv run python ar.py detect-structure <scan_id>`

**Acceptance Criteria:**
- ✅ Page mapping detects front matter / body / back matter correctly
- ✅ ToC parsing extracts all chapter titles + page numbers
- ✅ Chapter detection finds all major chapters (expected ~15-20)
- ✅ LLM validation cost < $0.30 per book
- ✅ Manual review confirms chapter boundaries are correct
- ✅ Tests pass (`pytest tests/pipeline/test_structure.py`)

**Estimated Time:** 4-5 days

---

### Week 3: Stage 5 Implementation
**Goal:** Create semantic chunks

**Tasks:**
1. Create `pipeline/5_chunks/` directory structure
2. Define `Chunk` and `ChunkManifest` schemas in `schemas.py`
3. Implement `create_chunks()` logic
4. Write unit tests for chunking logic
5. Test on `accidental-president` (validate chunk sizes, chapter alignment)
6. Add CLI command: `uv run python ar.py create-chunks <scan_id>`

**Acceptance Criteria:**
- ✅ All pages chunked into ~5-page segments
- ✅ No chunks cross chapter boundaries
- ✅ Chunk text is clean (headers/footers excluded)
- ✅ Manifest accurately indexes all chunks
- ✅ Processing time < 1 minute for 400 pages
- ✅ Tests pass (`pytest tests/pipeline/test_chunks.py`)

**Estimated Time:** 2-3 days

---

### Week 4: Integration & Testing
**Goal:** End-to-end validation

**Tasks:**
1. Create end-to-end test script (`tests/test_pipeline_e2e.py`)
2. Run full pipeline on `accidental-president` (stages 0-5)
3. Test on 2-3 additional books (different formats, sizes)
4. Document usage in `README.md`
5. Add examples to `docs/examples/pipeline_usage.md`
6. Update `CLAUDE.md` with new stage patterns
7. Update `docs/standards/` if new patterns emerged
8. Create GitHub issues for known limitations/future enhancements

**Acceptance Criteria:**
- ✅ Full pipeline runs without manual intervention
- ✅ Checkpoint resume works across all stages
- ✅ Cost tracking accurate end-to-end
- ✅ Output suitable for MCP server integration
- ✅ Documentation complete and accurate
- ✅ All tests pass (`pytest tests/`)

**Estimated Time:** 3-4 days

---

## Risks & Mitigations

### Risk 1: Chapter Detection Fails for Non-Standard Books
**Likelihood:** Medium
**Impact:** High (no chapters = chunking fails)

**Scenarios:**
- Book has no ToC
- Book uses custom heading styles (not detected by OCR)
- Book has nested sections (Parts → Chapters → Sections)
- Academic book with numbered sections instead of titled chapters

**Mitigation:**
1. **Graceful fallback:** If no chapters detected, create fixed-size chunks (every 20 pages = "pseudo-chapter")
2. **Manual override:** Allow user to specify chapter boundaries via JSON config file
3. **LLM full-book analysis:** If confidence < 0.5 for all chapters, use LLM to analyze entire book structure (~$0.50 cost)
4. **Test on diverse books:** Validate on 10+ books with different formats before declaring production-ready

**Monitoring:** Track chapter detection failures, build library of edge cases

---

### Risk 2: ToC Parsing Fails (Complex Formats)
**Likelihood:** Medium
**Impact:** Medium (cross-validation fails, but label-based detection still works)

**Scenarios:**
- ToC spans multiple pages (partial entries)
- ToC uses Roman numerals, special characters, multiple dots
- ToC is image-based (scanned, not OCR-ed)
- No ToC at all (older books, some fiction)

**Mitigation:**
1. **Robust regex patterns:** Handle common formats (Part I, Chapter 1, Section A)
2. **Fuzzy matching:** Allow ±3 page mismatch between ToC and detected chapters
3. **LLM fallback:** If parsing confidence < 0.7, ask LLM to parse ToC text (~$0.05)
4. **Skip ToC validation:** If parsing fails completely, rely solely on label detection (still accurate)

**Testing:** Build test suite with 20+ different ToC formats

---

### Risk 3: Page Number Mapping Fails
**Likelihood:** Low
**Impact:** Medium (book page references incorrect, but PDF page processing still works)

**Scenarios:**
- Book has no page numbers (front matter, some modern books)
- Page numbers in unusual locations (margins, not headers/footers)
- Multiple numbering schemes (preface uses Roman, appendix restarts at 1)

**Mitigation:**
1. **Allow missing mappings:** Store `book_page: null` for unnumbered pages
2. **Use OCR spatial heuristics:** Check expected header/footer locations if labels fail
3. **LLM extraction:** For ambiguous cases, ask LLM to identify page numbers from page image (~$0.01/page)
4. **User override:** Allow manual page mapping via JSON file

**Impact Assessment:** Even if mapping fails, pipeline still works (just less user-friendly page references)

---

### Risk 4: OCR/Correction Alignment Errors
**Likelihood:** Low
**Impact:** High (merge fails, pipeline halts)

**Scenarios:**
- Correction stage bug (skipped blocks)
- OCR and correction have different block counts
- Paragraph numbers don't match (data corruption)

**Mitigation:**
1. **Strict validation:** Fail fast if alignment is off (don't proceed with bad data)
2. **Debug files:** Save misaligned pages to `logs/debug/merge_errors/page_XXXX_debug.json`
3. **Checkpoint resume:** Don't checkpoint misaligned pages (allow retry without contaminating checkpoint)
4. **Alert user:** Provide clear error message with page number and mismatch details
5. **Data integrity checks:** Add validation to correction stage to prevent misalignment

**Recovery:** If alignment fails, user must re-run correction stage for affected pages

---

### Risk 5: LLM Validation Cost Exceeds Budget
**Likelihood:** Low
**Impact:** Medium (cost overrun)

**Scenarios:**
- Book has many ambiguous boundaries (50%+ low confidence)
- LLM validation prompts too large (context bloat)
- User processes 100s of books without monitoring costs

**Mitigation:**
1. **Cost limits:** Halt validation if cost exceeds $0.30 per book, flag for review
2. **Prompt optimization:** Use minimal viable context (3 pages, not 10)
3. **Adaptive validation:** Skip validation if first 5 chapters all pass with >0.95 confidence
4. **CLI flag:** `--skip-llm-validation` for cost-sensitive users (reduces accuracy slightly)
5. **Cost monitoring:** Log validation costs per chapter, alert if anomalies

**Budget:** At $0.20-0.25 per book, even 100 books = $20-25 (acceptable)

---

### Risk 6: Chunk Boundaries Split Important Content
**Likelihood:** Low
**Impact:** Low (MCP queries still work, audiobook may have awkward pauses)

**Scenarios:**
- Chunk ends mid-paragraph
- Chunk ends mid-quote or mid-dialogue
- Scene change happens mid-chunk

**Mitigation:**
1. **Chapter-aware chunking:** Never split across chapters (implemented)
2. **Future enhancement:** Semantic boundary detection (detect scene breaks, topic shifts)
3. **Overlap strategy:** Add 1-page overlap between chunks (optional parameter)
4. **MCP context expansion:** MCP server can fetch adjacent chunks if context insufficient

**Reality Check:** Fixed 5-page chunks are "good enough" for 80% of use cases. Perfect semantic chunking can be v2 feature.

---

## Success Criteria

### Must-Have (MVP - Week 4)

- ✅ **End-to-end pipeline:** Stages 0-5 run successfully on `accidental-president`
- ✅ **Chapter detection accuracy:** >90% of chapters detected correctly (manual validation)
- ✅ **Chunk creation:** All pages chunked with chapter awareness (no cross-chapter splits)
- ✅ **Cost target:** Total cost < $0.30 per book
- ✅ **Performance target:** Processing time < 5 minutes for 400-page book
- ✅ **Checkpoint reliability:** All stages resume correctly after interruption
- ✅ **Schema validation:** All output files validate against defined schemas
- ✅ **Test coverage:** >80% code coverage for stages 3-5
- ✅ **Documentation:** README, architecture doc, and standards docs updated

### Nice-to-Have (Future Enhancements)

**Version 2.0:**
- Semantic boundary detection for chunks (detect scene/topic breaks)
- Chunk overlap parameter (1-page overlap for context continuity)
- Multi-level ToC parsing (Parts → Chapters → Sections)
- Smart chapter title extraction (handle multi-line titles, subtitles)

**Version 3.0:**
- Chapter summary generation (1-sentence per chapter)
- Quote extraction (memorable quotes indexed separately)
- Character/entity extraction (build character index for fiction)
- Timeline extraction (events in chronological order for history books)

---

## Appendix

### A. Architecture Decision Record (ADR)

**ADR-001: Keep Full Files for Each Stage**
- Decision: Preserve OCR, corrected, AND processed files
- Rationale: Debugability > disk space savings
- Alternatives Considered: Overwrite corrected with processed (rejected - loses traceability)

**ADR-002: Liberal LLM Validation Strategy**
- Decision: Validate ALL chapter boundaries with LLM
- Rationale: Quality > cost ($0.20 negligible vs. pipeline value)
- Alternatives Considered: Validate only ambiguous cases (rejected - saved $0.10, risked accuracy)

**ADR-003: Page Number Mapping as Foundational Infrastructure**
- Decision: Build PDF ↔ Book page mapping in Stage 4
- Rationale: Enables ToC cross-validation and user-facing features
- Alternatives Considered: Skip mapping, use PDF pages only (rejected - poor UX)

**ADR-004: Chapter-Aware Fixed Chunking**
- Decision: 5-page fixed chunks, never cross chapters
- Rationale: Simple, predictable, "good enough" for 80% of use cases
- Alternatives Considered: Semantic boundary detection (deferred to v2 - added complexity)

**ADR-005: Three-Stage Architecture (3-5)**
- Decision: Merge → Structure → Chunks
- Rationale: Clear separation of concerns, resumable stages
- Alternatives Considered: Single structure stage (rejected - too long-running, hard to resume)

### B. Schema Reference

All schemas defined in:
- `pipeline/3_merge/schemas.py`
- `pipeline/4_structure/schemas.py`
- `pipeline/5_chunks/schemas.py`

### C. Testing Strategy

**Unit Tests:**
- `tests/pipeline/test_merge.py` - Merge logic, alignment validation
- `tests/pipeline/test_page_mapping.py` - Page number extraction, mapping logic
- `tests/pipeline/test_toc_parser.py` - ToC parsing, regex patterns
- `tests/pipeline/test_chapter_detection.py` - Chapter detection, cross-validation
- `tests/pipeline/test_chunks.py` - Chunking logic, chapter awareness

**Integration Tests:**
- `tests/test_pipeline_e2e.py` - Full pipeline (stages 0-5)

**Test Data:**
- `tests/fixtures/` - Sample pages, ToC examples, edge cases

### D. CLI Usage Examples

```bash
# Run full pipeline (stages 0-5)
uv run python ar.py pipeline accidental-president

# Run individual stages
uv run python ar.py merge accidental-president
uv run python ar.py detect-structure accidental-president
uv run python ar.py create-chunks accidental-president

# Stage-specific options
uv run python ar.py detect-structure accidental-president --skip-llm-validation
uv run python ar.py create-chunks accidental-president --pages-per-chunk=10

# Resume from checkpoint
uv run python ar.py merge accidental-president --resume

# Status and monitoring
uv run python ar.py status accidental-president
uv run python ar.py monitor accidental-president
```

### E. Related Documentation

- `docs/standards/` - Infrastructure patterns (checkpointing, LLM client, etc.)
- `docs/examples/pipeline_usage.md` - Usage examples and common workflows
- `README.md` - High-level overview and quick start
- `CLAUDE.md` - Development workflow and conventions

---

**End of Architecture Document**

*Version 1.0 | 2025-10-09 | Approved for Implementation*
