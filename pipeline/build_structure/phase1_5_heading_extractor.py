"""
Phase 1.5: Extract heading text from all chapter heading pages.

This phase runs AFTER ToC parsing and BEFORE structure analysis to extract
the actual heading text from pages marked as has_chapter_heading=True in the
labels report. This provides ground truth data to distinguish parts from chapters.

Cost: Free (no LLM calls, just reading merged page JSON)
Time: ~1-2 seconds
"""

import csv
import re
from pathlib import Path
from typing import Optional

from infra.pipeline.logger import PipelineLogger
from infra.storage.book_storage import BookStorage

from .schemas import HeadingData, HeadingEntry


def find_chapter_heading_pages(labels_report_path: Path) -> list[tuple[int, Optional[str]]]:
    """
    Find all pages marked as has_chapter_heading=True.

    Args:
        labels_report_path: Path to labels/report.csv

    Returns:
        List of (scan_page_num, printed_page_number) tuples
        printed_page_number is a string (may be roman numeral like 'xiv' or arabic like '42')
    """
    with open(labels_report_path, "r") as f:
        rows = list(csv.DictReader(f))

    heading_pages = []
    for row in rows:
        if row.get("has_chapter_heading") == "True":
            page_num = int(row["page_num"])
            printed_page = row.get("printed_page_number")
            # Keep as string to preserve roman numerals
            printed_page_str = printed_page.strip() if printed_page and printed_page.strip() else None
            heading_pages.append((page_num, printed_page_str))

    return heading_pages


def extract_heading_from_page(storage: BookStorage, page_num: int) -> str:
    """
    Extract heading text from the first blocks of a page.

    Args:
        storage: BookStorage instance
        page_num: Page number to read

    Returns:
        Extracted heading text (e.g., "Part IV", "17", "Chapter 1")
    """
    merged_storage = storage.stage("merged")
    page_data = merged_storage.load_page(page_num)

    # Extract text from first few blocks (headings are usually at top)
    heading_parts = []
    blocks = page_data.get("blocks", [])

    # Look at first 3 blocks max
    for block in blocks[:3]:
        paragraphs = block.get("paragraphs", [])
        for para in paragraphs[:2]:  # First 2 paragraphs per block
            text = para.get("text", "").strip()
            if text:
                heading_parts.append(text)

    # Join with spaces and clean up
    heading_text = " ".join(heading_parts).strip()

    # Truncate to reasonable length (headings shouldn't be long)
    if len(heading_text) > 200:
        heading_text = heading_text[:200] + "..."

    return heading_text


def is_part_heading(heading_text: str) -> bool:
    """
    Determine if heading text represents a part boundary.

    Args:
        heading_text: Extracted heading text

    Returns:
        True if heading contains "Part" keyword (case-insensitive)
    """
    # Look for "Part" followed by number/roman numeral
    # Examples: "Part I", "Part IV", "PART 2", etc.
    pattern = r'\bPart\s+[IVX\d]'
    return bool(re.search(pattern, heading_text, re.IGNORECASE))


def extract_headings(
    storage: BookStorage,
    labels_report_path: Path,
    logger: PipelineLogger,
) -> HeadingData:
    """
    Extract heading text from all chapter heading pages.

    Phase 1.5 of build-structure: Read actual heading text to inform structure analysis.

    Args:
        storage: BookStorage instance
        labels_report_path: Path to labels/report.csv
        logger: Pipeline logger

    Returns:
        HeadingData with all extracted headings
    """
    logger.info("Phase 1.5: Extracting heading text from chapter heading pages")

    # Find all chapter heading pages
    heading_pages = find_chapter_heading_pages(labels_report_path)

    if not heading_pages:
        logger.info("No chapter heading pages found")
        return HeadingData(headings=[], total_headings=0, part_count=0, chapter_count=0)

    logger.info("Found chapter heading pages", count=len(heading_pages))

    # Extract heading text from each page
    headings = []
    part_count = 0
    chapter_count = 0

    for page_num, printed_page in heading_pages:
        heading_text = extract_heading_from_page(storage, page_num)

        if not heading_text:
            logger.warning("No heading text extracted", page=page_num)
            continue

        is_part = is_part_heading(heading_text)

        if is_part:
            part_count += 1
        else:
            chapter_count += 1

        entry = HeadingEntry(
            page_num=page_num,
            heading_text=heading_text,
            is_part=is_part,
            printed_page_number=printed_page,
        )
        headings.append(entry)

        logger.debug(
            "Extracted heading",
            page=page_num,
            text=heading_text[:50],
            is_part=is_part,
        )

    heading_data = HeadingData(
        headings=headings,
        total_headings=len(headings),
        part_count=part_count,
        chapter_count=chapter_count,
    )

    logger.info(
        "Heading extraction complete",
        total=len(headings),
        parts=part_count,
        chapters=chapter_count,
    )

    return heading_data
