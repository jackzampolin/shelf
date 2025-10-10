"""
Substage 4a: Table of Contents Parsing

Finds TABLE_OF_CONTENTS labeled pages and uses LLM to parse them
into structured entries with chapter titles, levels, and page numbers.
"""

import json
import importlib
from datetime import datetime
from typing import List, Dict, Tuple
from pathlib import Path

import logging

from infra.llm_client import LLMClient

# Import from numeric module names using importlib
merge_schemas = importlib.import_module('pipeline.3_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')

structure_schemas = importlib.import_module('pipeline.4_structure.schemas')
TocEntry = getattr(structure_schemas, 'TocEntry')
TocOutput = getattr(structure_schemas, 'TocOutput')

logger = logging.getLogger(__name__)


def parse_toc(
    pages: List[MergedPageOutput],
    scan_id: str,
    output_dir: Path,
    model: str = "openai/gpt-4o-mini",
) -> TocOutput:
    """
    Parse Table of Contents from labeled pages using LLM.

    Process:
    1. Find all pages with TABLE_OF_CONTENTS classification
    2. Extract text from those pages
    3. Send to LLM to parse into structured entries
    4. Parse LLM JSON response into TocEntry objects
    5. Save to chapters/toc.json

    Args:
        pages: All merged pages
        scan_id: Scan identifier
        output_dir: Directory to save toc.json
        model: LLM model to use for parsing

    Returns:
        TocOutput: Parsed ToC with all entries

    Raises:
        ValueError: If no ToC pages found or LLM parsing fails
    """
    logger.info("Parsing Table of Contents...")

    # Step 1: Find ToC pages
    toc_pages = _find_toc_pages(pages)
    if not toc_pages:
        logger.warning("No TABLE_OF_CONTENTS pages found, returning empty ToC")
        return TocOutput(
            scan_id=scan_id,
            toc_pages=[],
            entries=[],
            parsing_method="llm",
            model_used=model,
            cost=0.0,
            total_entries=0,
            low_confidence_entries=0,
            timestamp=datetime.now().isoformat(),
        )

    logger.info(f"Found ToC on PDF pages: {toc_pages}")

    # Step 2: Extract text from ToC pages
    toc_text = _extract_toc_text(pages, toc_pages)
    logger.info(f"Extracted {len(toc_text)} characters of ToC text")

    # Step 3: Parse with LLM
    entries, cost = _parse_with_llm(toc_text, model)
    logger.info(f"Parsed {len(entries)} ToC entries (cost: ${cost:.4f})")

    # Step 4: Calculate statistics
    low_confidence_count = sum(1 for e in entries if e.confidence < 0.8)

    # Step 5: Build output
    toc_output = TocOutput(
        scan_id=scan_id,
        toc_pages=toc_pages,
        entries=entries,
        parsing_method="llm",
        model_used=model,
        cost=cost,
        total_entries=len(entries),
        low_confidence_entries=low_confidence_count,
        timestamp=datetime.now().isoformat(),
    )

    # Step 6: Save checkpoint
    output_file = output_dir / "toc.json"
    with open(output_file, "w") as f:
        f.write(toc_output.model_dump_json(indent=2))
    logger.info(f"Saved ToC output to {output_file}")

    return toc_output


def _find_toc_pages(pages: List[MergedPageOutput]) -> List[int]:
    """Find all pages with TABLE_OF_CONTENTS classification."""
    toc_pages = []
    for page in pages:
        has_toc = any(
            block.classification == "TABLE_OF_CONTENTS"
            for block in page.blocks
        )
        if has_toc:
            toc_pages.append(page.page_number)
    return toc_pages


def _extract_toc_text(pages: List[MergedPageOutput], toc_page_numbers: List[int]) -> str:
    """
    Extract full text from ToC pages.

    Only includes blocks classified as TABLE_OF_CONTENTS to avoid
    picking up headers/footers that might be on the same page.
    """
    toc_blocks = []

    for page in pages:
        if page.page_number not in toc_page_numbers:
            continue

        # Get only TABLE_OF_CONTENTS blocks
        page_toc_blocks = page.get_blocks_by_type("TABLE_OF_CONTENTS")

        for block in page_toc_blocks:
            # Collect all paragraph text from this block
            block_text = "\n".join(p.text for p in block.paragraphs)
            toc_blocks.append(f"[Page {page.page_number}]\n{block_text}")

    return "\n\n".join(toc_blocks)


def _parse_with_llm(toc_text: str, model: str) -> Tuple[List[TocEntry], float]:
    """
    Use LLM to parse ToC text into structured entries.

    The LLM extracts:
    - Chapter/section titles
    - Hierarchy level (Part, Chapter, Section)
    - Book page numbers (roman, arabic, or none)
    - Confidence in each extraction
    """
    system_prompt = """You are a Table of Contents parser. Extract structured ToC entries from the provided text.

For each entry, extract:
- title: The chapter/section title (clean, no page numbers)
- level: Hierarchy (0=Part, 1=Chapter, 2=Section, 3=Subsection)
- entry_type: One of: "part_heading", "chapter", "section", "subsection", "other"
- book_page: Page number as shown in ToC (e.g., "ix", "45", null if none)
- numbering_style: "roman", "arabic", or "none"
- confidence: Your confidence in this extraction (0.0-1.0)
- raw_text: The original text for this entry

Respond with a JSON object:
{
  "entries": [
    {
      "title": "Introduction",
      "level": 1,
      "entry_type": "chapter",
      "book_page": "ix",
      "numbering_style": "roman",
      "confidence": 0.95,
      "raw_text": "Introduction ix"
    },
    ...
  ]
}

Guidelines:
- Part headings have no page numbers
- Be generous with confidence - if structure is clear, use 0.9+
- If a line has dots/dashes between title and page, that's a chapter
- Watch for multi-line titles (they should be one entry)
- Roman numerals: i, ii, iii, iv, v, vi, vii, viii, ix, x, xi, xii, etc.
- Arabic numerals: 1, 2, 3, 4, etc."""

    user_prompt = f"""Parse this Table of Contents:

{toc_text}

Return structured JSON with all entries."""

    # Initialize LLM client
    client = LLMClient()

    # Define JSON parser
    def parse_json(response_text: str) -> Dict:
        """Parse LLM response as JSON, handling markdown code blocks."""
        # Strip markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]  # Remove ```json
        elif text.startswith("```"):
            text = text[3:]  # Remove ```
        if text.endswith("```"):
            text = text[:-3]  # Remove closing ```
        text = text.strip()

        # Parse JSON
        return json.loads(text)

    # Call LLM with JSON retry
    try:
        result, usage, cost = client.call_with_json_retry(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            json_parser=parse_json,
            temperature=0.0,
            max_retries=2,
        )

        # Parse into TocEntry objects
        entries = [TocEntry(**entry_data) for entry_data in result["entries"]]

        return entries, cost

    except Exception as e:
        logger.error(f"Failed to parse ToC with LLM: {e}")
        raise ValueError(f"ToC parsing failed: {e}")
