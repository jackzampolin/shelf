"""
Page Mapping Validator - Uses LLM to validate and correct page mapping

Given:
- ToC entries with book page numbers
- CHAPTER_HEADING labels showing where chapters appear in PDF
- Extracted page numbers from vision model (may have errors)

LLM analyzes the data and:
- Matches ToC entries to PDF pages
- Detects offset patterns
- Identifies front matter region
- Flags and corrects errors
"""

import json
from typing import List, Dict, Tuple
from pathlib import Path

import logging

from infra.llm_client import LLMClient

import importlib

# Import schemas
structure_schemas = importlib.import_module('pipeline.4_structure.schemas')
TocEntry = getattr(structure_schemas, 'TocEntry')
PageMapping = getattr(structure_schemas, 'PageMapping')

merge_schemas = importlib.import_module('pipeline.3_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')

logger = logging.getLogger(__name__)


def validate_page_mapping_with_llm(
    toc_entries: List[TocEntry],
    pages: List[MergedPageOutput],
    initial_mappings: List[PageMapping],
    model: str = "openai/gpt-4o-mini"
) -> Tuple[Dict[str, any], float]:
    """
    Use LLM to find ToC anchor points (match ToC entries to PDF pages).

    This is a MINIMAL LLM task - just match 10-15 ToC entries to their PDF pages.
    The actual page mapping interpolation is done deterministically.

    Args:
        toc_entries: Parsed ToC entries with book page numbers
        pages: All merged pages with CHAPTER_HEADING labels
        initial_mappings: Not used anymore (kept for compatibility)
        model: LLM model to use

    Returns:
        (anchor_dict, cost) - Dict with ToC title → PDF page mappings
    """
    logger.info("Finding ToC anchor points with LLM...")

    # Build minimal context for LLM
    context = _build_anchor_context(toc_entries, pages)

    # Call LLM with structured output
    client = LLMClient()

    system_prompt = """You are a ToC anchor matcher. Match Table of Contents entries to their PDF pages.

**Your task:** For each ToC entry with a book page number, find which PDF page it appears on.

**How to match:**
1. Look at CHAPTER_HEADING labels - these show where chapters start in the PDF
2. Match ToC title text to CHAPTER_HEADING text (fuzzy matching is ok)
3. Confirm with header text if available (e.g., header "39 / The Political Education" confirms book page 39)

**Important:**
- Only match entries that have book page numbers (skip Part headings without numbers)
- Return null for PDF page if you can't find a match
- Be confident - if CHAPTER_HEADING text is close to ToC title, that's a match"""

    user_prompt = f"""Match these ToC entries to their PDF pages:

{context}

Return the PDF page number where each ToC entry appears."""

    # Schema: ToC anchors (title → PDF page)
    response_schema = {
        "type": "object",
        "properties": {
            "anchors": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "toc_title": {"type": "string"},
                        "book_page": {"type": ["string", "null"]},
                        "pdf_page": {"type": ["integer", "null"]},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0}
                    },
                    "required": ["toc_title", "book_page", "pdf_page", "confidence"],
                    "additionalProperties": False
                }
            }
        },
        "required": ["anchors"],
        "additionalProperties": False
    }

    # Call LLM
    try:
        response, usage, cost = client.call(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "page_mapping_validation",
                    "strict": True,
                    "schema": response_schema
                }
            }
        )

        result = json.loads(response)
        logger.info(f"LLM anchor matching complete (cost: ${cost:.4f})")
        logger.info(f"Matched {len(result['anchors'])} ToC anchors")

        # Log anchors
        for anchor in result['anchors']:
            if anchor['pdf_page']:
                logger.info(f"  '{anchor['toc_title']}' (book page {anchor['book_page']}) → PDF page {anchor['pdf_page']}")

        return result, cost

    except Exception as e:
        logger.error(f"LLM validation failed: {e}")
        raise


def _build_anchor_context(
    toc_entries: List[TocEntry],
    pages: List[MergedPageOutput]
) -> str:
    """Build minimal context for ToC anchor matching."""
    lines = []

    # ToC entries to match
    lines.append("## Table of Contents Entries (to match)")
    for entry in toc_entries:
        if entry.book_page:  # Only entries with page numbers
            lines.append(f"- \"{entry.title}\" → book page {entry.book_page}")

    # Chapter heading locations (where to look for matches)
    lines.append("\n## CHAPTER_HEADING Labels (where chapters appear in PDF)")
    chapter_headings = []
    for page in pages:
        heading_blocks = page.get_blocks_by_type("CHAPTER_HEADING")
        if heading_blocks:
            for block in heading_blocks:
                for para in block.paragraphs:
                    if para.text:
                        chapter_headings.append({
                            "pdf_page": page.page_number,
                            "heading_text": para.text.strip()
                        })

    for ch in chapter_headings:
        lines.append(f"- PDF page {ch['pdf_page']}: \"{ch['heading_text']}\"")

    # Optional: Sample headers for confirmation
    lines.append("\n## Sample Header Text (for confirmation)")
    sample_count = 0
    for page in pages:
        if sample_count >= 20:
            break
        header_blocks = page.get_blocks_by_type("HEADER")
        if header_blocks:
            for block in header_blocks:
                for para in block.paragraphs:
                    if para.text:
                        lines.append(f"- PDF page {page.page_number}: \"{para.text.strip()}\"")
                        sample_count += 1
                        break

    return "\n".join(lines)
