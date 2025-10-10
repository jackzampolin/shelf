"""
Substage 4b: Page Mapping

Builds PDF page ↔ Book page mapping using ToC anchors and deterministic interpolation.

Strategy:
1. LLM finds ToC anchors (ToC title → PDF page)
2. Deterministic interpolation between anchors
3. Detect front/body/back matter from ToC structure
"""

import json
from datetime import datetime
from typing import List, Dict, Tuple
from pathlib import Path

import logging

import importlib

# Import schemas
merge_schemas = importlib.import_module('pipeline.3_merge.schemas')
MergedPageOutput = getattr(merge_schemas, 'MergedPageOutput')

structure_schemas = importlib.import_module('pipeline.4_structure.schemas')
PageMapping = getattr(structure_schemas, 'PageMapping')
PageMappingOutput = getattr(structure_schemas, 'PageMappingOutput')
TocEntry = getattr(structure_schemas, 'TocEntry')

logger = logging.getLogger(__name__)


def build_page_mapping_from_anchors(
    pages: List[MergedPageOutput],
    toc_entries: List[TocEntry],
    toc_anchors: List[Dict],
    scan_id: str,
    output_dir: Path,
) -> PageMappingOutput:
    """
    Build complete page mapping using ToC anchors and deterministic interpolation.

    Args:
        pages: All merged pages
        toc_entries: ToC entries from parsing
        toc_anchors: LLM-matched anchors (toc_title, book_page, pdf_page)
        scan_id: Scan identifier
        output_dir: Directory to save outputs

    Returns:
        PageMappingOutput: Complete page mapping
    """
    logger.info("Building page mapping from ToC anchors...")

    # Convert anchors to dict for easy lookup
    anchor_dict = {a['toc_title']: {'pdf_page': a['pdf_page'], 'book_page': a['book_page']}
                   for a in toc_anchors if a['pdf_page'] is not None}

    logger.info(f"Using {len(anchor_dict)} ToC anchors for interpolation")

    # Build anchor pairs (sorted by PDF page)
    anchor_pairs = _build_anchor_pairs(toc_entries, anchor_dict)

    # Interpolate between anchors to build full mapping
    mappings = _interpolate_page_numbers(pages, anchor_pairs)

    # Detect regions (front/body/back matter)
    front_matter, body, back_matter = _detect_regions_from_toc(toc_entries, anchor_dict, len(pages))

    # Classify each page
    for mapping in mappings:
        if mapping.pdf_page in front_matter:
            mapping.page_type = "front_matter"
        elif mapping.pdf_page in back_matter:
            mapping.page_type = "back_matter"
        else:
            mapping.page_type = "body"

    # Extract header text for validation
    for i, page in enumerate(pages):
        if i < len(mappings):
            mappings[i].header_text = _extract_header_text(page)

    # Statistics
    toc_match_count = sum(1 for m in mappings if m.toc_matched)
    header_validated_count = sum(1 for m in mappings if m.header_validated)
    unmapped_pages = sum(1 for m in mappings if m.book_page is None)

    # Build output
    output = PageMappingOutput(
        scan_id=scan_id,
        total_pages=len(pages),
        mappings=mappings,
        front_matter_pages=front_matter,
        body_pages=body,
        back_matter_pages=back_matter,
        toc_match_count=toc_match_count,
        header_validated_count=header_validated_count,
        unmapped_pages=unmapped_pages,
        timestamp=datetime.now().isoformat()
    )

    # Save output
    output_file = output_dir / "page_mapping.json"
    with open(output_file, "w") as f:
        f.write(output.model_dump_json(indent=2))
    logger.info(f"Saved page mapping to {output_file}")

    logger.info(
        f"Page mapping complete: {len(mappings)} pages, "
        f"{len(front_matter)} front matter, "
        f"{len(body)} body, "
        f"{len(back_matter)} back matter, "
        f"{unmapped_pages} unmapped"
    )

    return output


def _build_anchor_pairs(
    toc_entries: List[TocEntry],
    anchor_dict: Dict[str, Dict]
) -> List[Tuple[int, str, str]]:
    """
    Build sorted list of anchors: (pdf_page, book_page, numbering_style).

    Returns anchors sorted by PDF page for interpolation.
    """
    anchors = []
    for entry in toc_entries:
        if entry.title in anchor_dict and entry.book_page:
            pdf_page = anchor_dict[entry.title]['pdf_page']
            book_page = entry.book_page
            numbering_style = entry.numbering_style or "arabic"
            anchors.append((pdf_page, book_page, numbering_style))

    # Sort by PDF page
    anchors.sort(key=lambda x: x[0])

    logger.info(f"Built {len(anchors)} anchor pairs for interpolation:")
    for pdf_page, book_page, style in anchors:
        logger.info(f"  PDF {pdf_page} = book page {book_page} ({style})")

    return anchors


def _interpolate_page_numbers(
    pages: List[MergedPageOutput],
    anchor_pairs: List[Tuple[int, str, str]]
) -> List[PageMapping]:
    """
    Interpolate page numbers between anchors.

    For each anchor pair, fill in the pages between them with sequential numbering.
    """
    mappings = []

    for i, page in enumerate(pages):
        pdf_page = page.page_number

        # Find which anchor pair this page falls into
        book_page = None
        numbering_style = "none"
        toc_matched = False

        # Check if this is an anchor point
        for anchor_pdf, anchor_book, anchor_style in anchor_pairs:
            if pdf_page == anchor_pdf:
                book_page = anchor_book
                numbering_style = anchor_style
                toc_matched = True
                break

        # If not an anchor, interpolate
        if book_page is None:
            book_page, numbering_style = _interpolate_single_page(
                pdf_page, anchor_pairs
            )

        mapping = PageMapping(
            pdf_page=pdf_page,
            book_page=book_page,
            page_type="body",  # Will be reclassified later
            numbering_style=numbering_style,
            toc_matched=toc_matched,
            header_validated=False,
            header_text=None
        )
        mappings.append(mapping)

    return mappings


def _interpolate_single_page(
    pdf_page: int,
    anchor_pairs: List[Tuple[int, str, str]]
) -> Tuple[str | None, str]:
    """
    Interpolate a single page number based on surrounding anchors.

    Returns: (book_page, numbering_style)
    """
    if not anchor_pairs:
        return None, "none"

    # Find surrounding anchors
    before = None
    after = None

    for i, (anchor_pdf, anchor_book, anchor_style) in enumerate(anchor_pairs):
        if anchor_pdf < pdf_page:
            before = (anchor_pdf, anchor_book, anchor_style)
        elif anchor_pdf > pdf_page:
            after = (anchor_pdf, anchor_book, anchor_style)
            break

    # Before first anchor
    if before is None and after is not None:
        return None, "none"  # Unnumbered front matter

    # After last anchor
    if after is None and before is not None:
        pdf_offset = pdf_page - before[0]
        book_page = _add_page_number(before[1], pdf_offset, before[2])
        return book_page, before[2]

    # Between two anchors
    if before and after:
        pdf_offset = pdf_page - before[0]
        book_page = _add_page_number(before[1], pdf_offset, before[2])
        return book_page, before[2]

    # Fallback
    return None, "none"


def _add_page_number(base_page: str, offset: int, numbering_style: str) -> str | None:
    """Add offset to a page number (handles roman and arabic)."""
    if offset == 0:
        return base_page

    if numbering_style == "roman":
        # Convert roman to int, add offset, convert back
        base_int = _roman_to_int(base_page)
        if base_int is None:
            return None
        new_int = base_int + offset
        return _int_to_roman(new_int)

    elif numbering_style == "arabic":
        # Simple integer addition
        try:
            base_int = int(base_page)
            return str(base_int + offset)
        except ValueError:
            return None

    else:
        return None


def _roman_to_int(s: str) -> int | None:
    """Convert roman numeral to integer."""
    roman_map = {'i': 1, 'v': 5, 'x': 10, 'l': 50, 'c': 100, 'd': 500, 'm': 1000}
    s = s.lower()
    total = 0
    prev_value = 0

    for char in reversed(s):
        if char not in roman_map:
            return None
        value = roman_map[char]
        if value < prev_value:
            total -= value
        else:
            total += value
        prev_value = value

    return total


def _int_to_roman(num: int) -> str:
    """Convert integer to roman numeral (lowercase)."""
    val = [1000, 900, 500, 400, 100, 90, 50, 40, 10, 9, 5, 4, 1]
    syms = ['m', 'cm', 'd', 'cd', 'c', 'xc', 'l', 'xl', 'x', 'ix', 'v', 'iv', 'i']
    roman = ''
    for i in range(len(val)):
        count = num // val[i]
        if count:
            roman += syms[i] * count
            num -= val[i] * count
    return roman


def _detect_regions_from_toc(
    toc_entries: List[TocEntry],
    anchor_dict: Dict[str, Dict],
    total_pages: int
) -> Tuple[List[int], List[int], List[int]]:
    """
    Detect front/body/back matter regions using ToC structure.

    Strategy:
    - Front matter: Before first arabic-numbered entry (roman numerals)
    - Body: From first arabic-numbered entry to last main chapter
    - Back matter: After last main chapter (Notes, Index, Bibliography, etc.)
    """
    front_matter = []
    body = []
    back_matter = []

    # Find first arabic-numbered entry
    first_body_entry = None
    for entry in toc_entries:
        if entry.numbering_style == "arabic" and entry.title in anchor_dict:
            first_body_entry = entry
            break

    # Find first back matter entry (Notes, Index, etc.)
    back_matter_keywords = ['notes', 'index', 'bibliography', 'references', 'glossary']
    first_back_matter_entry = None

    for entry in toc_entries:  # Forward iteration to find FIRST back matter
        if entry.title in anchor_dict and entry.book_page:
            # Check if this is back matter
            if any(kw in entry.title.lower() for kw in back_matter_keywords):
                first_back_matter_entry = entry
                break  # Found first back matter entry

    # Determine PDF page ranges
    if first_body_entry and first_body_entry.title in anchor_dict:
        first_body_pdf = anchor_dict[first_body_entry.title]['pdf_page']
        front_matter = list(range(1, first_body_pdf))

    if first_back_matter_entry and first_back_matter_entry.title in anchor_dict:
        first_back_pdf = anchor_dict[first_back_matter_entry.title]['pdf_page']
        back_matter = list(range(first_back_pdf, total_pages + 1))

    # Body is everything between front and back
    if front_matter and back_matter:
        body = list(range(front_matter[-1] + 1, back_matter[0]))
    elif front_matter:
        body = list(range(front_matter[-1] + 1, total_pages + 1))
    elif back_matter:
        body = list(range(1, back_matter[0]))
    else:
        body = list(range(1, total_pages + 1))

    logger.info(f"Detected regions: front={len(front_matter)}, body={len(body)}, back={len(back_matter)}")

    return front_matter, body, back_matter


def _extract_header_text(page: MergedPageOutput) -> str | None:
    """Extract header text from page if present."""
    header_blocks = page.get_blocks_by_type("HEADER")
    if header_blocks:
        texts = []
        for block in header_blocks:
            for para in block.paragraphs:
                if para.text:
                    texts.append(para.text)
        return " ".join(texts) if texts else None
    return None
