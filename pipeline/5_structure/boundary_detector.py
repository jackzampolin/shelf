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
merge_schemas = importlib.import_module('pipeline.4_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')

structure_schemas = importlib.import_module('pipeline.5_structure.schemas')
TocEntry = getattr(structure_schemas, 'TocEntry')
PageMapping = getattr(structure_schemas, 'PageMapping')
ValidationResult = getattr(structure_schemas, 'ValidationResult')
VisionValidationResult = getattr(structure_schemas, 'VisionValidationResult')
ValidatedBoundary = getattr(structure_schemas, 'ValidatedBoundary')
ValidatedBoundariesOutput = getattr(structure_schemas, 'ValidatedBoundariesOutput')

# Import LLM client and PDF utilities
from infra.llm.client import LLMClient
from infra.utils.pdf import get_pages_from_book, image_to_base64

logger = logging.getLogger(__name__)


def detect_and_validate_boundaries(
    pages: List[MergedPageOutput],
    toc_entries: List[TocEntry],
    page_mappings: List[PageMapping],
    scan_id: str,
    book_dir: Path,
    model: str = "google/gemma-3-27b-it",
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

        validated, cost = _validate_boundary_with_vision(
            toc_entry=toc_entry,
            expected_pdf_page=expected_pdf,
            pages=pages,
            book_dir=book_dir,
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


def _prepare_vision_context(
    toc_entry: TocEntry,
    expected_pdf_page: int,
    pages: List[MergedPageOutput],
    book_dir: Path,
    window_size: int = 1,
) -> Dict:
    """
    Prepare context for vision model with configurable window size.

    Args:
        toc_entry: ToC entry being validated
        expected_pdf_page: Expected PDF page from page mapping
        pages: All merged pages
        book_dir: Path to book directory (for PDF access)
        window_size: Window radius in pages (1 = ±1 = 3 pages, 3 = ±3 = 7 pages)

    Returns:
        Dict with 'images' (base64 encoded) and 'json_context' (page data)
    """
    # Extract PDF images (±window_size)
    image_pages = list(range(expected_pdf_page - window_size, expected_pdf_page + window_size + 1))
    pdf_images = get_pages_from_book(book_dir, image_pages, dpi=150)

    # Build JSON context (window_size + 1 for text context)
    json_window = window_size + 1
    context_pages = []
    for page_num in range(expected_pdf_page - json_window, expected_pdf_page + json_window + 1):
        page = next((p for p in pages if p.page_number == page_num), None)
        if page:
            # Include first 10 blocks, truncate text to 500 chars
            blocks_data = []
            for block in page.blocks[:10]:
                if block.paragraphs:
                    text = block.paragraphs[0].text[:500].strip()
                    if text:
                        blocks_data.append({
                            "classification": block.classification,
                            "text": text
                        })

            context_pages.append({
                "pdf_page": page.page_number,
                "book_page": page.printed_page_number,
                "blocks": blocks_data
            })

    return {
        "images": [image_to_base64(img) for img in pdf_images],
        "json_context": context_pages,
        "expected": {
            "title": toc_entry.title,
            "book_page": toc_entry.book_page,
            "entry_type": toc_entry.entry_type,
            "level": toc_entry.level,
        },
        "window_size": window_size
    }


def _validate_boundary_with_vision(
    toc_entry: TocEntry,
    expected_pdf_page: int,
    pages: List[MergedPageOutput],
    book_dir: Path,
    model: str = "google/gemma-3-27b-it",
) -> Tuple[ValidatedBoundary | None, float]:
    """
    Validate a single boundary using vision model with progressive window expansion.

    Tries progressively wider windows if boundary not found:
    - First try: ±5 pages (11 pages total)
    - Second try: ±7 pages (15 pages total)
    - Third try: ±10 pages (21 pages total)
    - Fourth try: ±12 pages (25 pages total)

    Args:
        toc_entry: ToC entry being validated
        expected_pdf_page: Expected PDF page from page mapping
        pages: All merged pages
        book_dir: Path to book directory (for PDF access)
        model: Vision model to use

    Returns:
        (ValidatedBoundary | None, cost)
    """
    total_cost = 0.0

    # Progressive window sizes to try
    window_sizes = [5, 7, 10, 12]  # ±5 (11 pages), ±7 (15 pages), ±10 (21 pages), ±12 (25 pages)

    for window_size in window_sizes:
        window_desc = f"±{window_size} pages ({2*window_size + 1} total)"
        logger.info(f"Trying window {window_desc} for '{toc_entry.title}' at PDF {expected_pdf_page}")

        # Try this window size
        validated, cost = _try_vision_window(
            toc_entry, expected_pdf_page, pages, book_dir, model, window_size
        )
        total_cost += cost

        if validated:
            if window_size > 1:
                logger.info(
                    f"Found boundary via expanded window ({window_desc}): "
                    f"'{toc_entry.title}' at PDF {validated.pdf_page}"
                )
            return validated, total_cost

    # Not found in any window
    logger.warning(
        f"Could not find boundary for '{toc_entry.title}' after trying windows: "
        f"{', '.join(f'±{w}' for w in window_sizes)}"
    )
    return None, total_cost


def _try_vision_window(
    toc_entry: TocEntry,
    expected_pdf_page: int,
    pages: List[MergedPageOutput],
    book_dir: Path,
    model: str,
    window_size: int,
) -> Tuple[ValidatedBoundary | None, float]:
    """
    Try to validate a boundary using a specific window size.

    Returns:
        (ValidatedBoundary | None, cost)
    """
    # Prepare context (images + JSON)
    try:
        context = _prepare_vision_context(toc_entry, expected_pdf_page, pages, book_dir, window_size)
    except Exception as e:
        logger.error(f"Error preparing vision context: {e}")
        import traceback
        traceback.print_exc()
        return None, 0.0

    if not context.get("images"):
        logger.warning(f"No images available for PDF {expected_pdf_page}")
        return None, 0.0

    # Build vision prompt
    system_prompt = """You are a book structure validator using visual analysis of PDF pages.

VISUAL PATTERNS TO RECOGNIZE:
- **Part Dividers**: Full-page centered title, large decorative font, minimal text, often blank verso
- **Chapter Starts**: Chapter title (may be numbered) + body text begins, may have epigraphs or decorations
- **Section Headings**: Mid-page heading that subdivides a chapter, body text continues
- **Running Headers**: Small text at top of page that repeats across pages (book/chapter title) - NOT boundaries

IMPORTANT: Running headers are NOT boundaries. They appear on every page and just show the current chapter/book title.

Your task: Determine which page (if any) in the provided images contains the expected structural boundary.

Return your analysis as JSON with these exact fields:
- pdf_page: The PDF page number where the boundary actually starts (or null if not found)
- title: The actual title text you see at the boundary
- boundary_type: "part" | "chapter" | "section" | "subsection"
- confidence: 0.0-1.0 (how certain you are)
- visual_evidence: What you saw in the images that indicates this boundary
- reasoning: Why you classified it this way"""

    user_prompt = f"""Expected boundary from Table of Contents:
- Title: "{toc_entry.title}"
- Type: {toc_entry.entry_type}
- Book page: {toc_entry.book_page}
- Hierarchy level: {toc_entry.level}

JSON context (corrected OCR text from surrounding pages):
{json.dumps(context['json_context'], indent=2)}

QUESTION: Looking at the provided PDF page images, which page (if any) contains this structural boundary?
"""

    # Build multimodal messages
    messages = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                # Add images
                *[
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{img}"}
                    }
                    for img in context['images']
                ]
            ]
        }
    ]

    # Call vision model
    client = LLMClient()

    try:
        response, usage, cost = client.call(
            model=model,
            messages=messages,
            temperature=0.0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "vision_boundary_validation",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "pdf_page": {"type": ["integer", "null"]},
                            "title": {"type": "string"},
                            "boundary_type": {
                                "type": "string",
                                "enum": ["part", "chapter", "section", "subsection"]
                            },
                            "confidence": {"type": "number"},
                            "visual_evidence": {"type": "string"},
                            "reasoning": {"type": "string"}
                        },
                        "required": ["pdf_page", "title", "boundary_type", "confidence", "visual_evidence", "reasoning"],
                        "additionalProperties": False
                    }
                }
            }
        )

        # Parse response
        result = json.loads(response)

        if result['pdf_page'] is None:
            logger.warning(
                f"Vision model could not find boundary for '{toc_entry.title}' "
                f"in window around PDF {expected_pdf_page}: {result['reasoning']}"
            )
            return None, cost

        # Check if vision model corrected the page
        llm_corrected = (result['pdf_page'] != expected_pdf_page)

        # Get book page for the validated PDF page
        book_page = toc_entry.book_page  # Default to ToC's book page
        validated_page = next((p for p in pages if p.page_number == result['pdf_page']), None)
        if validated_page and validated_page.printed_page_number:
            book_page = validated_page.printed_page_number

        # Create ValidationResult (using existing schema for compatibility)
        validation_result = ValidationResult(
            is_correct=(not llm_corrected),
            correct_pdf_page=result['pdf_page'],
            correct_title=result['title'],
            confidence=result['confidence'],
            reasoning=f"{result['visual_evidence']} | {result['reasoning']}"
        )

        # Create ValidatedBoundary
        validated = ValidatedBoundary(
            pdf_page=result['pdf_page'],
            book_page=book_page,
            title=result['title'],
            detected_by="TOC_VISION_MAPPING",  # Distinguish vision validation
            toc_match=True,
            llm_validated=True,  # Vision model validated
            llm_corrected=llm_corrected,
            initial_confidence=0.9,  # High initial confidence from ToC
            final_confidence=result['confidence'],
            validation_result=validation_result,
        )

        if llm_corrected:
            logger.info(
                f"Vision model corrected boundary: '{toc_entry.title}' "
                f"PDF {expected_pdf_page} → {result['pdf_page']} "
                f"(type: {result['boundary_type']}, confidence: {result['confidence']:.2f})"
            )
        else:
            logger.info(
                f"Vision model confirmed boundary: '{toc_entry.title}' "
                f"at PDF {result['pdf_page']} "
                f"(type: {result['boundary_type']}, confidence: {result['confidence']:.2f})"
            )

        return validated, cost

    except Exception as e:
        logger.error(f"Error validating boundary with vision model: {e}")
        import traceback
        traceback.print_exc()
        return None, 0.0


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
