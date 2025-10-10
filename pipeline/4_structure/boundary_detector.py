"""
Substage 4c: Boundary Detection via Direct ToC Validation

Simple approach: For each ToC entry, validate the boundary with LLM using ±1 page window.
No noisy CHAPTER_HEADING label collection - just direct validation.
"""

import logging
from pathlib import Path
from typing import List, Dict, Tuple
import json
from datetime import datetime
import importlib

# Import schemas using importlib (numeric module names)
merge_schemas = importlib.import_module('pipeline.3_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')

structure_schemas = importlib.import_module('pipeline.4_structure.schemas')
TocEntry = getattr(structure_schemas, 'TocEntry')
PageMapping = getattr(structure_schemas, 'PageMapping')
ValidationResult = getattr(structure_schemas, 'ValidationResult')
ValidatedBoundary = getattr(structure_schemas, 'ValidatedBoundary')
ValidatedBoundariesOutput = getattr(structure_schemas, 'ValidatedBoundariesOutput')

# Import LLM client
from infra.llm_client import LLMClient

logger = logging.getLogger(__name__)


def detect_and_validate_boundaries(
    pages: List[MergedPageOutput],
    toc_entries: List[TocEntry],
    page_mappings: List[PageMapping],
    scan_id: str,
    model: str = "openai/gpt-4o-mini",
) -> ValidatedBoundariesOutput:
    """
    Detect and validate chapter boundaries directly from ToC entries.

    For each ToC entry:
    1. Look up expected PDF page from page mapping
    2. Create ±1 page window (3 pages total)
    3. Ask LLM to validate boundary location
    4. Return validated boundary

    Args:
        pages: All merged pages
        toc_entries: ToC entries from parsing
        page_mappings: PDF ↔ book page mappings
        scan_id: Scan identifier
        model: LLM model to use for validation

    Returns:
        ValidatedBoundariesOutput: Validated boundaries with LLM corrections
    """
    logger.info("Detecting and validating chapter boundaries from ToC...")

    boundaries = []
    total_cost = 0.0

    # Build lookup maps
    page_map = {m.pdf_page: m for m in page_mappings}
    pages_by_pdf = {p.page_number: p for p in pages}

    # Process each ToC entry
    for idx, toc_entry in enumerate(toc_entries):
        # Skip entries without page numbers (e.g., "Part I" headings)
        if toc_entry.book_page is None:
            logger.info(f"Skipping ToC entry without page number: {toc_entry.title}")
            continue

        # Find expected PDF page
        expected_pdf = _find_pdf_page_for_book_page(toc_entry.book_page, page_mappings)

        if expected_pdf is None:
            logger.warning(
                f"Could not find PDF page for ToC entry '{toc_entry.title}' "
                f"(book page {toc_entry.book_page})"
            )
            continue

        # Validate with LLM using ±1 page window
        logger.info(
            f"Validating boundary for '{toc_entry.title}' "
            f"(expected PDF {expected_pdf}, book {toc_entry.book_page})"
        )

        validated, cost = _validate_boundary_with_llm(
            toc_entry=toc_entry,
            expected_pdf_page=expected_pdf,
            pages_by_pdf=pages_by_pdf,
            model=model,
        )

        if validated:
            boundaries.append(validated)
            total_cost += cost

    # Create output
    llm_corrections = len([b for b in boundaries if b.llm_corrected])
    high_confidence = len([b for b in boundaries if b.final_confidence >= 0.9])
    low_confidence = len([b for b in boundaries if b.final_confidence < 0.7])

    output = ValidatedBoundariesOutput(
        scan_id=scan_id,
        boundaries=boundaries,
        total_boundaries=len(boundaries),
        llm_corrections_made=llm_corrections,
        high_confidence_count=high_confidence,
        low_confidence_count=low_confidence,
        model_used=model,
        validation_cost=total_cost,
        avg_validation_time_seconds=0.0,  # Could track if needed
        timestamp=datetime.now().isoformat(),
    )

    logger.info(
        f"Boundary validation complete: {output.total_boundaries} boundaries validated, "
        f"{output.llm_corrections_made} corrections made, cost: ${output.validation_cost:.4f}"
    )

    return output


def _find_pdf_page_for_book_page(
    book_page: str,
    page_mappings: List[PageMapping],
) -> int | None:
    """Find PDF page number for a given book page number."""
    for mapping in page_mappings:
        if mapping.book_page == book_page:
            return mapping.pdf_page
    return None


def _validate_boundary_with_llm(
    toc_entry: TocEntry,
    expected_pdf_page: int,
    pages_by_pdf: Dict[int, MergedPageOutput],
    model: str = "openai/gpt-4o-mini",
) -> Tuple[ValidatedBoundary | None, float]:
    """
    Validate a single boundary with LLM using ±1 page window.

    Returns: (ValidatedBoundary | None, cost)
    """
    # Build 3-page context window (expected - 1, expected, expected + 1)
    window_pages = [expected_pdf_page - 1, expected_pdf_page, expected_pdf_page + 1]
    context_pages = []

    for pdf_page in window_pages:
        if pdf_page in pages_by_pdf:
            context_pages.append(pages_by_pdf[pdf_page])

    if not context_pages:
        logger.warning(f"No pages available in window for PDF {expected_pdf_page}")
        return None, 0.0

    # Build context for LLM
    context = _build_validation_context(toc_entry, expected_pdf_page, context_pages)

    # Call LLM
    client = LLMClient()

    system_prompt = """You are a chapter boundary validator. Your job is to confirm where a chapter actually starts.

You'll receive:
- A ToC entry with expected title and page number
- A 3-page window (expected page ± 1)

Your task:
1. Find which page the chapter actually starts on (within the 3-page window)
2. Confirm or correct the chapter title
3. Assess confidence (0.0-1.0)

Return JSON with:
- pdf_page: The actual PDF page where chapter starts
- title: The actual chapter title (corrected if needed)
- confidence: 0.9-1.0 (clear chapter start), 0.6-0.8 (likely but ambiguous), 0.3-0.5 (uncertain)
- notes: Brief explanation of what you found

If you can't find the chapter boundary in this window, return null for pdf_page."""

    user_prompt = context

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
                    "name": "boundary_validation",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "pdf_page": {"type": ["integer", "null"]},
                            "title": {"type": "string"},
                            "confidence": {"type": "number"},
                            "notes": {"type": "string"}
                        },
                        "required": ["pdf_page", "title", "confidence", "notes"],
                        "additionalProperties": False
                    }
                }
            }
        )

        # Parse response
        result = json.loads(response)

        if result['pdf_page'] is None:
            logger.warning(
                f"LLM could not find boundary for '{toc_entry.title}' "
                f"in window around PDF {expected_pdf_page}: {result['notes']}"
            )
            return None, cost

        # Check if LLM corrected the page
        llm_corrected = (result['pdf_page'] != expected_pdf_page)

        # Get book page from mapping - find the actual book page for the validated PDF page
        book_page = toc_entry.book_page  # Default to ToC's book page

        # Create ValidationResult
        validation_result = ValidationResult(
            is_correct=(not llm_corrected),
            correct_pdf_page=result['pdf_page'],
            correct_title=result['title'],
            confidence=result['confidence'],
            reasoning=result['notes']
        )

        # Create ValidatedBoundary with all required schema fields
        validated = ValidatedBoundary(
            pdf_page=result['pdf_page'],
            book_page=book_page,
            title=result['title'],
            detected_by="TOC_MAPPING",  # We found this from ToC + page mapping
            toc_match=True,  # All our boundaries are from ToC
            llm_validated=True,  # We validated with LLM
            llm_corrected=llm_corrected,
            initial_confidence=0.9,  # High initial confidence (from ToC)
            final_confidence=result['confidence'],  # LLM's confidence
            validation_result=validation_result,
        )

        if llm_corrected:
            logger.info(
                f"LLM corrected boundary: '{toc_entry.title}' "
                f"PDF {expected_pdf_page} → {result['pdf_page']} "
                f"(confidence: {result['confidence']:.2f})"
            )

        return validated, cost

    except Exception as e:
        logger.error(f"Error validating boundary with LLM: {e}")
        import traceback
        traceback.print_exc()
        return None, 0.0


def _build_validation_context(
    toc_entry: TocEntry,
    expected_pdf_page: int,
    context_pages: List[MergedPageOutput],
) -> str:
    """Build context for LLM validation."""
    lines = []

    # What we expect
    lines.append("## Expected Chapter Boundary (from Table of Contents)")
    lines.append(f"- Title: \"{toc_entry.title}\"")
    lines.append(f"- Book page: {toc_entry.book_page}")
    lines.append(f"- Expected PDF page: {expected_pdf_page}")
    lines.append("")

    # Show 3-page window
    lines.append("## 3-Page Window (Expected ± 1)")
    lines.append("")

    for page in context_pages:
        lines.append(f"### PDF Page {page.page_number} (Book page: {page.printed_page_number or 'unknown'})")
        lines.append("")

        # Show text blocks (first 500 chars of each)
        for block in page.blocks[:5]:  # First 5 blocks
            if block.paragraphs:
                text = block.paragraphs[0].text[:500].strip()
                if text:
                    lines.append(f"**{block.classification}:** {text}")
                    lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)
